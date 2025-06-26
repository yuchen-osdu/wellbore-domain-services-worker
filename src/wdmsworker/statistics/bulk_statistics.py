import io
import hashlib
import asyncio
import itertools
import pandas as pd
from datetime import datetime, timedelta, timezone
from typing import List, Iterable, Iterator, Tuple

from osdu.core.api.storage import exceptions as osdu_storage_exception

from . import stats_reader
from .models import StatisticsComputationMeta, BulkStatisticsStatus, InternalStatisticsComputationMeta
from .exceptions import (
    ComputationRunningError,
    RequestedCurvesError,
    StatisticsNotFoundError,
    ComputationNotCompleteError,
    BulkCatalogNotFoundError,
)

from ..bulk.catalog import BulkCatalog, async_load_bulk_catalog_with_blob_storage
from ..bulk.constants import READ_MAX_TOTAL_VALUES_COUNT_FILTERED, READ_MAX_COLUMNS_COUNT
from ..bulk.dataframe import get_requested_columns
from ..bulk.storage_path_builder import join
from ..bulk import storage_path_builder

from ..logger import get_logger


def grouper(n: int, container: Iterable) -> Iterator[tuple]:
    """
    Return generator over a sub-list of 'n' elements of the given 'container'
    >>> list(grouper(4,['A', 'B', 'C', 'D', 'E', 'F']))
    returns: [('A', 'B', 'C', 'D'), ('E', 'F')]
    """
    n = int(n)
    it = iter(container)
    while chunk := tuple(itertools.islice(it, n)):
        yield chunk


def get_columns_count(max_number_values: int, max_columns_count: int, nb_rows: int, nb_cols: int) -> int:
    """
    Return the numbers of columns to be read at once in parquet files to stay under a given limit of maximum values.

    @param max_number_values: maximum number of values to be read at once, within several bulk files
    @param max_columns_count: maximum number of columns to be read whenever the limit is reached
    @param nb_rows: number of rows per bulk files (which must have the same shape)
    @param nb_cols: number of columns per bulk files (which must have the same shape)

        >>> get_columns_count(max_number_values=100_000, max_columns_count=500, nb_rows=10_000, nb_cols=10)
        >>> 10

        >>>> get_columns_count(max_number_values=100_000, max_columns_count=100, nb_rows=100_000, nb_cols=10)
        >>> 1
    """

    total_nb_values = nb_rows * nb_cols
    block_count = max(total_nb_values / max_number_values, 1)
    wanted_nb_col = max(int(nb_cols / block_count), 1)
    return min(max_columns_count, wanted_nb_col)


class BulkStatistics:
    # maximum number of bulk values to be fetched and computed per batch
    _paging_size_per_batch: int = READ_MAX_TOTAL_VALUES_COUNT_FILTERED
    # maximum number of columns of data to be fetched per batch of bulk files
    _max_cols_per_batch: int = READ_MAX_COLUMNS_COUNT

    # Maximum number of time the computation of statistics can be triggered
    _max_computation_retry_count: int = 3
    # Duration before allowing to re-computation statistics
    _duration_before_recompute: timedelta = timedelta(hours=1)

    _stats_api_version = "1"

    _valid_values_label = "totalCount"
    _renaming_stats_labels = {"count": "nonAbsentValuesCount"}
    _percentiles = [0.10, 0.5, 0.90]

    def __init__(self, storage, tenant):
        self._storage = storage
        self._tenant = tenant

    def _statistics_base_path(self, record_id: str, bulk_id: str):
        """Return the base path for bulk data statistics for current version"""
        return storage_path_builder.record_statistics_base_path(
            record_id, bulk_id, self._stats_api_version, base_directory=None
        )

    def _statistics_data_path(self, record_id: str, bulk_id):
        """Return the path for where statistics files are saved for a given record and bulk id"""
        return join(self._statistics_base_path(record_id, bulk_id), "data")

    def _check_recomputation_allowed(self, statistics_meta: InternalStatisticsComputationMeta):
        """
        Return true if statistics computation can be triggered again based on stats meta,
        else raise an ComputationRunningError.
        """
        if statistics_meta.meta.computation_status == BulkStatisticsStatus.Complete:
            raise ComputationRunningError("Statistics computation already complete")

        if (
            statistics_meta.meta.computation_status == BulkStatisticsStatus.Error
            and statistics_meta.computation_attempt >= self._max_computation_retry_count
        ):
            raise ComputationRunningError(
                f"Statistics computation has already failed {self._max_computation_retry_count} times. ABORT"
            )

        computations_status = statistics_meta.meta.computation_status
        expire_date = statistics_meta.last_computation_date + self._duration_before_recompute
        if computations_status == BulkStatisticsStatus.Running or (
            computations_status == BulkStatisticsStatus.Started and expire_date > datetime.utcnow()
        ):
            raise ComputationRunningError(
                "Statistics computation is already running for less than"
                f" {self._duration_before_recompute}. Please retry after {expire_date}"
            )

        statistics_meta.meta.computation_status = BulkStatisticsStatus.Started
        statistics_meta.computation_attempt += 1
        statistics_meta.last_computation_date = datetime.utcnow()

    async def _fetch_bulk_batch(self, catalog: BulkCatalog, columns: Tuple[str]) -> pd.DataFrame:
        """
        Read requested columns over bulk data parquet files and return it into one DataFrame.

        Data to be fetched can be in several files that possibly contains other unwanted columns.
        Requested Columns are fetched in each file provided by the bulk_catalog
         and then concatenate into one pd.DataFrame.
        """
        return await stats_reader.read_bulk_for_stats(self._storage, self._tenant, catalog, columns)

    @staticmethod
    def _compute_statistics_batch(bulk_df: pd.DataFrame, catalog) -> pd.DataFrame:
        """
        Perform statistics computation on given piece of bulk data
        Note: Column 'std' (standard deviation) can be missing from results, when bulk data are made of date dtype.
              Indeed, 'std' columns is NaN value, and it is ignored from resulting dataframe.
        """

        try:
            computed_stats = bulk_df.describe(percentiles=BulkStatistics._percentiles, exclude=[object, bool])
        except ValueError:
            # if input values cannot be processed because of excluded dtypes
            return pd.DataFrame()

        if "std" not in computed_stats.index:
            # The standard deviation column 'std' is omitted from df.describe() result when
            # all the dtypes of input dataframe are date/datetime.
            # To prevent the omission of 'std' column when reading parquet files later on,
            # the 'std' row is manually added.
            computed_stats.loc["std"] = pd.NaT

        computed_stats = computed_stats.astype("string").transpose()
        computed_stats[BulkStatistics._valid_values_label] = str(catalog.nb_rows)
        computed_stats.rename(columns=BulkStatistics._renaming_stats_labels, inplace=True)

        return computed_stats

    async def _process_bulk_batch(self, catalog: BulkCatalog, columns: Tuple[str], record_id: str, bulk_uri: str):
        """
        Entrypoint to run statistics computation: fetch pieces of bulk data, compute and save results

        @param catalog: bulk data catalog
        @param columns: selected columns to be computed
        @param record_id: record id on which computation will be performed
        @param bulk_uri: URI of bulk data on which computation will be performed
        """
        bulk_df = await self._fetch_bulk_batch(catalog, columns)

        computed_stats = self._compute_statistics_batch(bulk_df, catalog)

        await self._save_statistics_batch(computed_stats, record_id, bulk_uri)

    async def _save_statistics_batch(self, df_statistics: pd.DataFrame, record_id: str, bulk_id: str):
        """Save given statistic to parquet file, file path is determined with record_id and bulk_id"""

        if df_statistics.empty:
            return

        bulk_statistics_data_path = self._statistics_data_path(record_id, bulk_id)
        col_start = hashlib.sha1(df_statistics.index[0].encode()).hexdigest()[:10]
        col_end = hashlib.sha1(df_statistics.index[-1].encode()).hexdigest()[:10]

        filename = f"statistics_{col_start}-{col_end}.parquet"
        full_file_path = join(bulk_statistics_data_path, filename)

        parquet_content = df_statistics.to_parquet(None, index=True, engine="pyarrow")
        await self._storage.upload(self._tenant, full_file_path, io.BytesIO(parquet_content))

    async def trigger_stats_computation(self, columns_count_per_batch, existing_columns, catalog, record_id, bulk_uri):
        """
        Create several batch of statistics' computation per group of columns to be read at once,
        it is determined by the value of columns_count_per_batch.

        @return the list of routines
        """

        computation_routines = [
            self._process_bulk_batch(catalog, group_columns, record_id, bulk_uri)
            for group_columns in grouper(columns_count_per_batch, existing_columns)
        ]
        if not computation_routines:
            get_logger().warning(
                f"Bulk statistics - nothing to compute for record id '{record_id}' with bulk-uri '{bulk_uri}'"
            )
        else:
            get_logger().info(
                f"Bulk statistics - computation triggered for record id '{record_id}'"
                f" with bulk-uri '{bulk_uri}', started_futures count: {len(computation_routines)}"
            )

        return computation_routines

    async def compute_bulk_statistics(self, record_id: str, bulk_uri: str, record_version: int):
        """
        Start statistics' computation on whole bulk data of one record identified by its record_id and its bulk_uri.

        This computation in run per batch of columns of the bulk data, identified by record_id + bulk_uri.
        Each batch: fetch bulk data, compute statistics and save data statistics into blob storage

        Bulk information come from bulk catalog.

        Computation statistics relies on meta-data file: to determine state of computation, error handling and
        return the meta information to end-user. This file is stored close to bulk data of provided record_id.

        @param record_id: record id on which computation will be performed
        @param record_version: record version on which computation will be performed. The value is only stored in metadata.
        @param bulk_uri: URI of bulk data on which computation will be performed
        """
        catalog = await async_load_bulk_catalog_with_blob_storage(self._storage, self._tenant, record_id, bulk_uri)
        if not catalog:
            raise BulkCatalogNotFoundError()

        bulk_statistics_path = self._statistics_base_path(record_id, bulk_uri)
        try:
            internal_statistics_meta = await self._fetch_statistics_meta_file(bulk_statistics_path)
            self._check_recomputation_allowed(internal_statistics_meta)
        except (osdu_storage_exception.ResourceNotFoundException, FileNotFoundError):
            public_meta = StatisticsComputationMeta(
                computationStartDatetime=datetime.now(timezone.utc),
                recordId=record_id,
                recordVersion=record_version,
                computationStatus=BulkStatisticsStatus.Started,
            )
            internal_statistics_meta = InternalStatisticsComputationMeta(
                lastComputationDate=datetime.now(timezone.utc), computationAttempt=1, meta=public_meta
            )

        await self._push_statistics_meta_file(bulk_statistics_path, internal_statistics_meta, overwrite_meta_file=True)

        existing_columns = catalog.all_columns
        nb_rows = catalog.nb_rows
        nb_cols = len(existing_columns)
        columns_count_per_batch = get_columns_count(
            self._paging_size_per_batch, self._max_cols_per_batch, nb_rows, nb_cols
        )

        stats_computation_routines = await self.trigger_stats_computation(
            columns_count_per_batch, existing_columns, catalog, record_id, bulk_uri
        )

        internal_statistics_meta.meta.computation_status = BulkStatisticsStatus.Running
        await self._push_statistics_meta_file(bulk_statistics_path, internal_statistics_meta, overwrite_meta_file=True)

        return await self._set_statistics_file_as_complete(
            stats_computation_routines, bulk_statistics_path, internal_statistics_meta
        )

    async def _set_statistics_file_as_complete(self, stats_computation_routines, bulk_statistics_path, stats_meta_data):
        """
        Update meta-data file to mark statistics computation as complete

        @param stats_computation_routines list of coroutines to be awaited
        @param bulk_statistics_path: statistics meta file path
        @param stats_meta_data: statistics meta-data to be saved
        """

        results = await asyncio.gather(*stats_computation_routines, return_exceptions=True)
        errors = [r for r in results if (isinstance(r, BaseException))]

        if errors:
            stats_meta_data.meta.computation_status = BulkStatisticsStatus.Error
            get_logger().exception(
                f"An error has occurred when computing statistics for record '{stats_meta_data.meta.record_id}'",
                exc_info=errors[0],
            )
        else:
            stats_meta_data.meta.computation_status = BulkStatisticsStatus.Complete

        await self._push_statistics_meta_file(bulk_statistics_path, stats_meta_data, overwrite_meta_file=True)
        return stats_meta_data

    async def _fetch_statistics(self, bulk_statistics_data_path: str, columns: List[str]):
        """
        Read parquet files of computed statistics, then filter rows according to given columns.
        """

        all_objects = await self._storage.list_objects(self._tenant, prefix=bulk_statistics_data_path + "/")

        async def _load_single_df(s, t, f) -> pd.DataFrame:
            parquet_content = await s.download(t, f)
            return pd.read_parquet(io.BytesIO(parquet_content))

        read_parquet_routines = [
            _load_single_df(self._storage, self._tenant, o) for o in all_objects if o.endswith(".parquet")
        ]
        pd_files = await asyncio.gather(*read_parquet_routines)

        statistics_df = pd.concat(pd_files)
        return statistics_df.filter(items=columns, axis=0)

    async def _push_statistics_meta_file(
        self, bulk_statistics_path: str, stats_meta_data: InternalStatisticsComputationMeta, overwrite_meta_file: bool
    ):
        """
        Update meta-data file of statistics computation with given status of given stats_meta_data.
        """

        file_path = join(bulk_statistics_path, "statistics.json")
        stats_meta_content = stats_meta_data.model_dump_json(by_alias=True)

        # todo: etag should be used here to avoid unwanted overwrite
        await self._storage.upload(self._tenant, file_path, stats_meta_content, overwrite=overwrite_meta_file)

        return stats_meta_data

    async def _fetch_statistics_meta_file(self, bulk_statistics_path) -> InternalStatisticsComputationMeta:
        """Read statistics meta file at given path"""

        file_path = join(bulk_statistics_path, "statistics.json")
        blob_content = await self._storage.download(self._tenant, file_path)
        return InternalStatisticsComputationMeta.model_validate_json(blob_content)

    async def get_bulk_statistics(
        self, record_id: str, bulk_uri: str, curves_selection: List[str] | None
    ) -> Tuple[pd.DataFrame, StatisticsComputationMeta]:
        """
        @return The statistics data of given record identified by its record_id and bulk_uri

        @param curves_selection: name of columns to be fetched
        @param record_id: record id on which computation has been performed
        @param bulk_uri: URI of bulk data on which computation has been performed
        """
        catalog = await async_load_bulk_catalog_with_blob_storage(self._storage, self._tenant, record_id, bulk_uri)
        if not catalog:
            raise BulkCatalogNotFoundError()

        bulk_statistics_path = self._statistics_base_path(record_id, bulk_uri)
        try:
            internal_statistics_meta = await self._fetch_statistics_meta_file(bulk_statistics_path)
        except (osdu_storage_exception.ResourceNotFoundException, FileNotFoundError):
            raise StatisticsNotFoundError("Statistics do not exist")

        if internal_statistics_meta.meta.computation_status == BulkStatisticsStatus.Error:
            return pd.DataFrame(), internal_statistics_meta.meta

        elif internal_statistics_meta.meta.computation_status != BulkStatisticsStatus.Complete:
            raise ComputationNotCompleteError("Statistics computation not finished yet")

        if curves_selection is None:
            requested_columns = catalog.all_columns
        else:
            requested_columns, curves_non_existent, _ = get_requested_columns(curves_selection, catalog.all_columns)
            if curves_non_existent:
                raise RequestedCurvesError("Requested curves unknown")

        # todo: find a way to return 400 if requested columns are only not computable columns

        bulk_statistics_data_path = self._statistics_data_path(record_id, bulk_uri)
        stats_df = await self._fetch_statistics(bulk_statistics_data_path, requested_columns)

        return stats_df, internal_statistics_meta.meta
