# Copyright 2023 Schlumberger
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from io import BytesIO
from dataclasses import dataclass
from typing import List, Tuple
from itertools import repeat, chain
from asyncio import gather, create_task

import pandas as pd
from natsort import natsorted
from osdu.core.api.storage.blob_storage_base import BlobStorageBase
from osdu.core.api.storage import exceptions as blob_storage_errors

from ..model.filtering_model import BulkFilters, IndexFilters
from ..logger import get_logger
from ..capture_timings import timeit, capture_timings
from ..model.json_orient import JSONOrient
from ..model.mime_types import MimeType, MimeTypes
from .chunk_meta import ChunkMeta
from .filtering import ValueFilters, apply_bulk_filters
from .errors import FilteringError
from . import errors
from . import constants

from .catalog import BulkCatalog
from . import storage_path_builder
from .dataframe import (
    ColumnSelection,
    get_requested_columns,
    sort_dataframe_column,
    re_column_array,
    reorder_dataframe_columns,
    expand_columns,
    filter_by_index,
    get_row_count_and_columns,
    dump_df,
)

# blob storage exception mapping
bulk_error_mapping = {
    blob_storage_errors.ResourceNotFoundException: errors.CurvesNotFoundError,
}


@dataclass(frozen=True, eq=False, repr=False)
class ReadResult:
    content: bytes | str
    mime_type: MimeType


def _dataframe_filters_and_reorder_columns(
    final_df: pd.DataFrame,
    bulk_read_filters: BulkFilters,
):
    """Drop not needed columns and reorder needed one if necessary. Then apply bulk data values filters, index filters
    :param final_df: result dataframe to be refined
    :bulk_read_filters: regroup all necessary information to filters input dataframe
    :returns a refined dataframe
    """

    if bulk_read_filters.value_filters and bulk_read_filters.value_filters.has_filter():
        with timeit("apply filtering on final dataframe"):
            final_df = apply_bulk_filters(final_df, bulk_read_filters.value_filters)

    if bulk_read_filters.curves_order_requested:
        with timeit("apply reorder_dataframe_columns"):
            final_df = reorder_dataframe_columns(final_df, bulk_read_filters.requested_columns)
    else:
        any_curve_array = bulk_read_filters.curves_are_array
        if any_curve_array is None:
            # at this stage, if value is not set then compute it from df columns
            try:
                any_curve_array = any(re_column_array.match(c) for c in final_df.columns.tolist())
            except TypeError:
                # likely due to old V0 storage using non string in column, do not re-order
                get_logger().error(f"dataframe with invalid column type, found {final_df.columns.dtype}")

        if any_curve_array:
            # trigger natural sorting only if columns has arrays curves
            with timeit("sort_dataframe_columns"):
                final_df = sort_dataframe_column(final_df)

    # apply offset/limit parameters on potential smaller df
    return filter_by_index(final_df, bulk_read_filters.index_filters.offset, bulk_read_filters.index_filters.limit)


async def get_chunk_path_outside_session(storage: BlobStorageBase, tenant, record_id: str, bulk_id: str) -> str:
    base_chunk_path = storage_path_builder.bulk_path_level_1(record_id, bulk_id, base_directory=None)
    # need to perform a `ls` to know the parquet file
    chunk_paths = await storage.list_objects(tenant, prefix=storage_path_builder.join(base_chunk_path, ""))

    # failure cases
    if len(chunk_paths) > 1:
        # it could be a case of the very first storage version, all chunk were merged without producing catalog.
        # so last chance before error. Still only supports single parquet so might not cover all cases.
        # filter out no-parquet files (meta data files of Dask), if a single parquet file left, let's continue
        # otherwise raise a not supported case error.
        chunk_paths = [chunk_path for chunk_path in chunk_paths if chunk_path.endswith(".parquet")]
        if len(chunk_paths) != 1:
            # several parquet chunks without catalog, not supported
            get_logger().warning(
                f"cannot process {record_id} bulk_id {bulk_id}, multiple parquet files found without catalog,"
                f" {len(chunk_paths)} partitions found"
            )
            raise errors.BulkCaseNotSupportedError("multiple chunks without catalog")

    if len(chunk_paths) == 0:
        # last chance, it could be bulk stored with the very first storage, so direct single parquet file, no extension
        chunk_path = bulk_id
    else:
        chunk_path = chunk_paths[0]
    return chunk_path


@capture_timings("read_bulk_outside_session")
@errors.map_errors(bulk_error_mapping)  # type: ignore
async def read_bulk_outside_session(
    storage: BlobStorageBase,
    tenant,
    record_id: str,
    bulk_id: str,
    accept_type: MimeType,
    orient: JSONOrient | None,
    offset: int | None = None,
    limit: int | None = None,
    curves_selection: ColumnSelection | None = None,
    filters_params: ValueFilters | None = None,
    describe: bool | None = None,
) -> ReadResult:
    bulk_read_filters = _validate_parameters_no_catalog(offset, limit, None, filters_params)

    chunk_path = await get_chunk_path_outside_session(storage, tenant, record_id, bulk_id)
    if curves_selection is None:
        # non curves filter
        return await _build_response_from_single_chunk(
            storage, tenant, chunk_path, accept_type, orient, filters=bulk_read_filters, describe=describe
        )

    # there's no curves selection so need to load dataframe entirely
    df = await _load_single_dataframe_from_storage(storage, tenant, chunk_path)
    catalog = BulkCatalog.from_single_dataframe(record_id, chunk_path, df)

    _, bulk_read_filters = _validate_parameters(catalog, offset, limit, curves_selection, filters_params)

    df = _dataframe_filters_and_reorder_columns(df, bulk_read_filters)
    if describe:
        return _build_response_from_describe(*get_row_count_and_columns(df))
    return await _build_response_from_df(df, accept_type, orient)


@errors.map_errors(bulk_error_mapping)  # type: ignore
async def read_bulk(
    storage: BlobStorageBase,
    tenant,
    bulk_catalog: BulkCatalog,
    accept_type: MimeType,
    orient: JSONOrient | None,
    offset: int | None = None,
    limit: int | None = None,
    curves_selection: ColumnSelection | None = None,
    filters_params: ValueFilters | None = None,
    describe: bool | None = None,
) -> ReadResult:
    """
    attempt a fast track read on some circumstances, for now:
        - parquet format only
        - no filter
        - chunk should be broken down perfectly column wise, each column is inside one and only one chunk (chunk
        may contain several columns)
    in any other cases, it raises ReadFastTrackCaseNotSupportedException
     :param storage: storage
     :param tenant: tenant
     :param bulk_catalog: bulk catalog
     :param accept_type: out mime format
     :param orient: out mime format
     :param offset: offset
     :param limit: limit
     :param curves_selection: curves_selection, note: slice notation must be resolved before
     :param filters_params: filters to be applied on bulk dataframe columns
     :param describe: if true the result will be a JSon content with the number of rows and the column list else
                    the result will be the bulk data in the accept_type format
     :return: ReadResult
     :throw: ReadBulkCaseNotSupportedException,
             ReadBulkInvalidParameter,
             BulkCurvesNotFound,
             TooManyColumnsRequested,
             TooManyValuesRequested
    """

    columns_to_load, bulk_read_filters = _validate_parameters(
        bulk_catalog, offset, limit, curves_selection, filters_params
    )
    base_chunk_path = storage_path_builder.record_path_level_0(bulk_catalog.record_id, base_directory=None)

    # ---------- case of single chunk -----------------------------
    # TODO try to use direct forward in case requested columns == single chunk all columns
    if bulk_catalog.chunk_count == 1:  # only one chunk
        for chunk_path in bulk_catalog.get_chunk_paths():
            if bulk_catalog.is_single_file_chunk(chunk_path):
                return await _build_response_from_single_chunk(
                    storage,
                    tenant,
                    storage_path_builder.join(base_chunk_path, chunk_path),
                    accept_type,
                    orient,
                    columns_to_load=columns_to_load,
                    filters=bulk_read_filters,
                    describe=describe,
                )

    # If describe is activated, we will load only necessary columns, the one used by the filter
    # It involves creating a new filter in order to set the minimum set of columns to load

    describe_filter, filtered_columns_to_load = await _describe_filter_and_columns(bulk_read_filters, describe)

    actual_columns_to_load = filtered_columns_to_load or columns_to_load

    # figures out the number of chunks involved, only one path each
    with timeit("bulk_catalog.filter_group_for_columns"):
        chunk_groups = bulk_catalog.filter_group_for_columns(actual_columns_to_load)

    # not putting offset, limit here because each chunk may not cover the full bulk index
    # by the way it might be possible to do something before concat
    index_df_task = create_task(_read_index(storage, tenant, bulk_catalog))

    load_chunk_df_coros = [
        load_same_shape_dataframes_from_storage(
            storage,
            tenant,
            [storage_path_builder.join(base_chunk_path, p) for p in chunk_group.paths],
            [col for col in actual_columns_to_load if col in chunk_group.labels],
        )
        for chunk_group in chunk_groups
    ]

    with timeit(f"load {len(chunk_groups)} chunk dataframes and index dataframes"):
        dfs = await gather(*load_chunk_df_coros)  # chunks

    global_index = await index_df_task

    # concat df + select rows if needed
    with timeit(f"concat {len(dfs)} dataframes"):
        # TODO check concat when dfs are smaller than index
        final_df = pd.concat(chain(repeat(pd.DataFrame(index=global_index), 1), dfs), axis=1, copy=False)

    # drop extra columns, reorder columns if needed, then apply values filters and index filters
    final_df = _dataframe_filters_and_reorder_columns(final_df, describe_filter or bulk_read_filters)

    if describe:
        # The list of column of the dataframe is reduced compared to what asked the user,
        # only columns used in filter were loaded.
        nb_row, columns = await _describe_force_columns(bulk_read_filters, final_df)
        return _build_response_from_describe(nb_row, columns)
    # build the final response by serializing the dataframe into requested format
    return await _build_response_from_df(final_df, accept_type, orient)


async def _describe_force_columns(bulk_read_filters: BulkFilters, final_df: pd.DataFrame) -> Tuple[int, List[str]]:
    """When describe is computed with filters, we get a smaller dataframe with less columns,
    si we need to force the columns before returnung the columns"""
    nb_row, columns = get_row_count_and_columns(final_df)
    if (
        bulk_read_filters.value_filters
        and bulk_read_filters.value_filters.has_filter()
        and bulk_read_filters.requested_columns
    ):
        columns = bulk_read_filters.requested_columns
    return nb_row, columns


def _validate_parameters_no_catalog(
    offset: int | None,
    limit: int | None,
    curves_selection: ColumnSelection | None,
    bulk_filters: ValueFilters | None = None,
) -> BulkFilters:
    requested_columns = None if curves_selection is None else expand_columns(curves_selection)
    return BulkFilters(
        index_filters=IndexFilters(offset, limit),
        value_filters=bulk_filters,
        curves_are_array=None,
        requested_columns=requested_columns,
        curves_order_requested=True if curves_selection else False,
    )


def _validate_parameters(
    bulk_catalog: BulkCatalog,
    offset: int | None,
    limit: int | None,
    curves_selection: ColumnSelection | None,
    bulk_filters: ValueFilters | None = None,
) -> tuple[list[str], BulkFilters]:
    """
    validate case for fast track. It will throw ReadFastTrackCaseNotSupportedException if not supported given the
     parameters provided.
     It will throw either BulkCurvesNotFound, TooManyColumnsRequested or TooManyValuesRequested respectively if the
     curves selection doesn't match a column, if too many columns requested or involves too many values.
    return: tuple columns_to_load, BulkFilters. If columns_to_load is
    """
    try:
        index_filters = IndexFilters(offset, limit)
    except ValueError as e:
        raise errors.InvalidParameterError from e

    any_curves_array = None
    # ---------- first check if fast track can be applied -----------------------------
    # get the actual column to fetch from the given curve selection
    if curves_selection:
        requested_columns, curves_non_existent, any_curves_array = get_requested_columns(
            curves_selection, bulk_catalog.all_columns
        )
        if curves_non_existent:
            raise errors.CurvesNotFoundError(f"curves={curves_non_existent}")
    else:
        if len(bulk_catalog.all_columns) > constants.READ_MAX_COLUMNS_COUNT:
            raise errors.TooManyColumnsError(len(bulk_catalog.all_columns), constants.READ_MAX_COLUMNS_COUNT)
        requested_columns = natsorted(bulk_catalog.all_columns)

    extra_filtering_cols = set()
    if bulk_filters and bulk_filters.has_filter():
        invalid_columns = bulk_filters.columns - bulk_catalog.all_columns
        if invalid_columns:
            raise FilteringError(f"Requested columns '{list(invalid_columns)}' for filtering do not exist")
        # add columns needed for filtering which are not yet in columns
        extra_filtering_cols = {
            filtering_col for filtering_col in bulk_filters.columns if filtering_col not in set(requested_columns)
        }

    # validate the column count requested
    if len(requested_columns) > constants.READ_MAX_COLUMNS_COUNT:
        raise errors.TooManyColumnsError(len(requested_columns), constants.READ_MAX_COLUMNS_COUNT)

    # validate the values count before any filtering
    total_values_unfiltered = bulk_catalog.nb_rows * len(requested_columns)
    if total_values_unfiltered > constants.READ_MAX_TOTAL_VALUES_COUNT_UNFILTERED:
        raise errors.TooManyValuesError(total_values_unfiltered, constants.READ_MAX_TOTAL_VALUES_COUNT_UNFILTERED)

    # validate the values after filtering
    filtered_row_count = index_filters.row_count(bulk_catalog.nb_rows)
    index_filters.update_from_row_count(filtered_row_count)

    total_values_filtered = filtered_row_count * len(requested_columns)

    if total_values_filtered > constants.READ_MAX_TOTAL_VALUES_COUNT_FILTERED:
        raise errors.TooManyValuesError(total_values_filtered, constants.READ_MAX_TOTAL_VALUES_COUNT_FILTERED)

    columns_to_load = [*requested_columns, *extra_filtering_cols]

    return columns_to_load, BulkFilters(
        index_filters=IndexFilters(offset, limit),
        value_filters=bulk_filters,
        curves_are_array=any_curves_array,
        requested_columns=requested_columns,
        curves_order_requested=True if curves_selection else False,
    )


# @capture_timings('_build_response_from_df')
async def _build_response_from_df(df: pd.DataFrame, accept_type: MimeType, orient: JSONOrient | None) -> ReadResult:
    """serialize the dataframe into parquet and construct the http response"""

    df.index.name = None  # similar to 'df_render'
    with timeit(f"dataframe of shape {df.shape} to {accept_type}"):
        try:
            content = dump_df(df, accept_type, orient)
            return ReadResult(content, accept_type)
        except ValueError as e:
            raise errors.BulkUnprocessableError() from e


async def _load_single_dataframe_from_storage(storage: BlobStorageBase, tenant, obj_path: str, columns_to_load=None):
    """download and load a single dataframe selecting columns, and index based by position if offset and/or
    limit are provided"""
    # limit the concurrency to not overwhelm the service
    with timeit("download dataframe from storage"):
        content = await storage.download(tenant, obj_path)
    with timeit("loading parquet from dataframe"):
        content = BytesIO(content)
        return pd.read_parquet(content, columns=columns_to_load)


async def _expand_chunk_paths(
    storage: BlobStorageBase,
    tenant,
    obj_paths: List[str],
) -> List[str]:
    """
    the goal of this deal with dataframe saved by Dask with multi partition. In this case the path is not an actual
    parquet file but a folder containing multiple parquet files. Unfortunately there's no way to know how many
    files but listing objects in this folder with a name format `part.X.parquet`.
    Usually there's a single folder to expand so the following is kept simple.
    """
    result = []
    for p in obj_paths:
        if ChunkMeta.is_a_chunk_file(p):
            result.append(p)
        else:
            get_logger().debug(f"dask multipart detected for path {p}")
            list_result = await storage.list_objects(tenant, prefix=storage_path_builder.join(p, "part."))
            part_count = len([op for op in list_result if op.endswith("parquet")])  # for sure there's a better way
            # iterate on count to ensure the order for the later concat
            result.extend((storage_path_builder.join(p, f"part.{i}.parquet") for i in range(part_count)))

    return result


# @capture_timings('load_same_shape_dataframes_from_storage')
async def load_same_shape_dataframes_from_storage(
    storage: BlobStorageBase,
    tenant,
    obj_paths: List[str],
    columns=None,
) -> pd.DataFrame:
    """
    IMPORTANT: all dataframe should share the same columns ans types without any overlap on vertical axe. Meaning
    all can be concat horizontally (concat(dataframes, axis=0) )
    For now, due to lack of metadata, offset, limit will by applied if and and only if the resulting dataframe have
    same nb rows than the global index (if none, no slice applied)
    """
    # TODO could save the download and load of dataframe if we'd have a way to know the start/end of each chunk

    obj_paths = await _expand_chunk_paths(storage, tenant, obj_paths)
    dfs = await gather(*[_load_single_dataframe_from_storage(storage, tenant, path, columns) for path in obj_paths])

    # Note when concatenating of rows, order matters
    df = dfs[0] if len(dfs) == 1 else pd.concat(dfs, axis=0, copy=False)
    return df


# @capture_timings('_read_index')
async def _read_index(storage: BlobStorageBase, tenant, bulk_catalog: BulkCatalog) -> pd.Index:
    if not bulk_catalog.index_path:
        get_logger().warning(f"not index file for record {bulk_catalog.record_id}")
        return pd.Index([])
    index_path = storage_path_builder.join(
        storage_path_builder.record_path_level_0(bulk_catalog.record_id, base_directory=None), bulk_catalog.index_path
    )
    index_df = await _load_single_dataframe_from_storage(storage, tenant, index_path)
    return index_df.index


async def _build_response_from_single_chunk(
    storage: BlobStorageBase,
    tenant,
    blob_path,
    accept_type: MimeType,
    orient: JSONOrient | None,
    *,
    columns_to_load=None,
    filters: BulkFilters,
    describe: bool | None = None,
) -> ReadResult:
    # only one chunk
    if (
        describe  # describe prevents the fast track, we need to get the dataframe
        or filters.curves_order_requested
        or filters.index_filters.offset
        or filters.index_filters.limit
        or accept_type == MimeTypes.JSON
        or filters.value_filters
        and filters.value_filters.has_filter()
    ):
        # possible optimization when calling with describe
        # - if columns_to_load is empty:    it means catalog is not available so no optim possible
        # - if columns_to_load is not empty
        #   - if filter is not empty:   we can load only index + col on which filters apply, apply filter,
        #     get nb row and use col list from columns_to_load
        describe_filter = None
        filtered_columns_to_load = None
        if columns_to_load and describe:
            describe_filter, filtered_columns_to_load = await _describe_filter_and_columns(filters, describe)

        df = await _load_single_dataframe_from_storage(
            storage, tenant, blob_path, filtered_columns_to_load or columns_to_load
        )
        df = _dataframe_filters_and_reorder_columns(df, describe_filter or filters)
        if describe:
            nb_row, columns = get_row_count_and_columns(df)
            if columns_to_load:  # Need to use columns from the original filter
                nb_row, columns = await _describe_force_columns(filters, df)
            return _build_response_from_describe(nb_row, columns)
        return await _build_response_from_df(df, accept_type, orient)
    else:
        # easy fast track, just forward it
        return await _forward_parquet(storage, tenant, blob_path)


# @capture_timings('_forward_parquet')
async def _forward_parquet(storage: BlobStorageBase, tenant, parquet_path) -> ReadResult:
    content = await storage.download(tenant, parquet_path)

    # simply forward content as-it
    return ReadResult(content, MimeTypes.PARQUET)


# TODO similar as the one in read_routers, need to factorize
def build_json_str_from_describe(nb_row: int, columns: List[str]) -> str:
    """for performance reason in case of many columns we build the response ourselve instead of using JSONRessponse"""
    columns_string = str(columns).replace("'", '"') if columns is not None else "null"
    nb_rows_str = f"{nb_row}" if nb_row is not None else "null"
    return f"{'{'}\"numberOfRows\":{nb_rows_str}, \"columns\":{columns_string}{'}'}"


def _build_response_from_describe(nb_row: int, columns: List[str]) -> ReadResult:
    return ReadResult(build_json_str_from_describe(nb_row, columns), MimeTypes.JSON)


async def _describe_filter_and_columns(
    bulk_read_filters: BulkFilters, describe: bool | None
) -> Tuple[BulkFilters | None, List[str] | None]:
    """If describe is activated, we will load only necessary columns, the ones used by the filter
    It involves creating a new filter in order to set the minimum set of columns to load"""

    describe_filter = None
    filtered_columns_to_load = None
    if describe and bulk_read_filters.value_filters and bulk_read_filters.value_filters.has_filter():
        filtered_columns_to_load = list(bulk_read_filters.value_filters.columns)
        describe_filter = BulkFilters(
            index_filters=bulk_read_filters.index_filters,
            value_filters=bulk_read_filters.value_filters,
            curves_are_array=bulk_read_filters.curves_are_array,
            requested_columns=filtered_columns_to_load,
            curves_order_requested=bulk_read_filters.curves_order_requested,
        )
    return describe_filter, filtered_columns_to_load
