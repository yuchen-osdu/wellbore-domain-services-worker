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

"""Module dataframe manipulation functions"""

import re
from contextlib import suppress
from typing import Iterable, Dict, List, Tuple, Optional, Set
from io import BytesIO, StringIO
from functools import partial

from natsort import natsorted

import pandas as pd
import numpy as np
import pyarrow.parquet as pq
from pyarrow import Table

from ..model.json_orient import JSONOrient
from ..model.mime_types import MimeType, MimeTypes
from ..model.describe import DataframeBasicDescribe, ColumnDescribe
from ..logger import get_logger

re_column_array = re.compile(r"^(?P<name>.+)\[(?P<start>[^:]+):?(?P<stop>.*)\]$")
re_column_array_int = re.compile(r"^(?P<name>.+)\[(?P<idx>[0-9]+)\]$")


def group_curve_columns(all_columns: Iterable[str], include_non_array=True) -> Dict[str, List[str]]:
    """
    check column name/label to detect and group array.
    :param all_columns: column
    :param include_non_array: the `False` (default) the result does not include column that are not array
    :return: Dictionary curve name to column name/lablel. The column lists preserve the order from the input.

    Example with `include_non_array` at `False` (default), i.e. non array not included
    >>> group_curve_columns(['A', 'B', 'C[0]', 'C[1]', 'D[0]', 'D[1]', 'D[2]'], False)
    {'C': ['C[0]', 'C[1]'], 'D': ['D[0]', 'D[1]', 'D[2]']}

    Example with `include_non_array` at `True` (default), i.e. non array included
    >>> group_curve_columns(['A', 'B', 'C[0]', 'C[1]', 'D[0]', 'D[1]', 'D[2]'], True)
    {'A': ['A'], 'B': ['B'], 'C': ['C[0]', 'C[1]'], 'D': ['D[0]', 'D[1]', 'D[2]']}
    """

    array_col: Dict[str, List[str]] = {}
    for c in all_columns:
        match_result = re_column_array.match(c)
        if match_result:
            array_col.setdefault(match_result["name"], []).append(c)
        elif include_non_array:
            array_col[c] = [c]
    return array_col


def columns_to_slices(columns: Iterable[str]) -> List[str]:
    """
    try to group columns of an array as slice notation
    `["A", "C[1]", "C[4]", "C[3]", "C[2]", "C[2]", "C[6]"]` become `["A", "C[1:6]"]`
    :param columns:
    :return: list of columns or slices when possible
    """
    array_col: Dict[str, List[str]] = {}
    result = []
    for c in columns:
        match_result = re_column_array_int.match(c)
        if match_result:
            array_col.setdefault(match_result["name"], []).append(match_result["idx"])
        else:
            result.append(c)
    for c, indexes in array_col.items():
        if len(indexes) == 1:
            result.append(f"{c}[{indexes[0]}]")
            continue

        np_arr = np.array(indexes, int)
        amin, amax = np_arr.min(), np_arr.max()
        if len(indexes) == amax + 1 - amin:
            result.append(f"{c}[{amin}:{amax}]")
        else:
            result.extend(f"{c}[{idx}]" for idx in indexes)
    return result


def get_array_columns(all_columns: Iterable[str]) -> Dict[str, List[str]]:
    """
    returns array curves only (non curve array are filtered out) and all associated columns.
    The returned object is an array 'curve name' <-> list of columns labels
    """
    return group_curve_columns(all_columns, False)


def match_full_slice_pattern(column_label: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    match single column label to a full slice. Always return a tuple
    if not an array like or no full slice pattern return `None`, `None`, `None`
    if match an array then return a tuple, first `name`, second `start`, third `stop`

    example full slice pattern
    >>> match_full_slice_pattern('C[0:10]')
    ('C', '0', '10')

    example non array nor partial slice
    >>> match_full_slice_pattern('C')
    (None, None, None)
    >>> match_full_slice_pattern('C[0]')
    (None, None, None)
    >>> match_full_slice_pattern('C[0:]')
    (None, None, None)
    >>> match_full_slice_pattern('C[:10]')
    (None, None, None)
    """

    match_result = re_column_array.match(column_label)
    if match_result is None:
        return None, None, None  # i.e. not a slice pattern

    start, stop = match_result["start"], match_result["stop"]
    if start and stop:
        return match_result["name"], start, stop
    return None, None, None  # not a full slice pattern


ColumnSelection = List[str]
""" List of column/curve. Support (full) slice notation. """


def expand_columns(column_selection: ColumnSelection) -> List[str]:
    """
    resolve slice notation

    examples:
    >>> expand_columns(["A", "B"])
    ["A", "B"]

    >>> expand_columns(["A", "C[1:3]"])
    ["A", "C[1]", "C[2]", "C[3]"]
    """
    result: List[str] = []
    for sel in column_selection:
        curve_name_slice, slice_start, slice_stop = match_full_slice_pattern(sel)
        if curve_name_slice:
            result.extend(
                f"{curve_name_slice}[{i}]"
                for i in range(int(slice_start), int(slice_stop) + 1)  # type: ignore
            )
        else:
            result.append(sel)
    return result


def get_requested_columns(column_selection: ColumnSelection, columns: Set[str]) -> Tuple[List[str], List[str], bool]:
    """
    filter columns given a list of selection. If one selection match a curve array, the result will contain all
    associated columns. Support (full) slice notation.
    Returns two lists and a boolean, the first contains the selected columns, the second contain selection that doesn't
     match any columns, the last bool is True if requested, at least  columns are part of an array else False:

    basic example:
    >>> get_requested_columns(['A', 'C'], {'A', "B", "C", "D"})
    (['A', 'C'], [], False)

    with non matching selection:
    >>> get_requested_columns(['A', 'X'], {'A', "B", "C", "D"})
    (['A'], ['X'], False)

    selection a curve array:
    >>> get_requested_columns(['A'], {'A[0]', "A[1]", "A[2]", "D"})
    (['A[0]', 'A[1]', 'A[2]'], [], True)

    array slicing
    >>> get_requested_columns(['A[2:4]'], {'A[0]', "A[1]", "A[2]", "A[3]", "A[4]", "A[5]", "A[6]"})
    (['A[2]', 'A[3]', 'A[4]'], [], True)
    """
    selected = {}
    curves_non_existent: List[str] = []
    curves_array: Optional[Dict[str, List[str]]] = None

    for sel in column_selection:
        if sel in columns:
            selected[sel] = 1
            continue

        if curves_array is None:
            curves_array = get_array_columns(columns)

        matching_columns = {sel}
        curve_name_slice, slice_start, slice_stop = match_full_slice_pattern(sel)
        if curve_name_slice:
            # means sel is a form CURVE_NAME[VALUE or SLICE],
            if slice_start and slice_stop:  # full slice expression provided
                with suppress(ValueError):  # suppress int conversion exceptions
                    # TODO we may want to support floating point values ?
                    matching_columns = set(
                        f"{curve_name_slice}[{i}]" for i in range(int(slice_start), int(slice_stop) + 1)
                    )
        elif sel in curves_array:  # no slicing + known as array => add all of them
            matching_columns = set(curves_array[sel])

        if not columns.issuperset(matching_columns):
            curves_non_existent.extend(matching_columns.difference(columns))
        else:
            # TODO what is the point to sort here?
            #  could be a bottleneck for big array (> 100 000)
            selected.update({column: 1 for column in sort_column_labels(matching_columns)})

    any_curves_array = curves_array is not None and len(curves_array) > 0
    return list(selected.keys()), curves_non_existent, any_curves_array


def sort_column_labels(column_labels: Iterable[str]) -> List[str]:
    """natural sort"""
    # TODO natsorted, could be a bottleneck for big array (> 100 000)
    #  must find better approach than brutal sort all, because many columns comes from array which are
    #  Curve[0] ... Curve[N], so it should to be handle this in a smarter way

    # TODO it also might be faster in real cases to first group columns into curves and then sort each sub groups
    # curve_groups = group_curve_columns(column_labels)
    # sorted_curves = natsorted(curve_groups.keys())
    # return list(
    #     chain.from_iterable(
    #         (natsorted(curve_groups[curve]) for curve in sorted_curves)
    #     )
    # )
    return natsorted(column_labels)


def reorder_dataframe_columns(df: pd.DataFrame, curve_selection: List[str] | None) -> pd.DataFrame:
    """Reorder dataframe columns order according curve_selection if reordering is necessary"""
    if curve_selection and list(curve_selection) != df.columns.tolist():
        return df[curve_selection]

    return df


def sort_dataframe_column(df: pd.DataFrame) -> pd.DataFrame:
    """Apply natural sorting on dataframe columns"""
    sorted_columns = sort_column_labels(df.columns)
    return reorder_dataframe_columns(df, sorted_columns)


def load_df(file_like_data, content_type: MimeType) -> pd.DataFrame:
    if isinstance(file_like_data, bytes):
        file_like_data = BytesIO(file_like_data)
    else:
        file_like_data = StringIO(file_like_data)

    if content_type == MimeTypes.PARQUET:
        return pd.read_parquet(file_like_data)
    elif content_type == MimeTypes.JSON:
        return pd.read_json(
            path_or_buf=file_like_data,
            orient="split",
            dtype=False,  # Ensure float are not cast to integer if X.00
            convert_dates=True,  # Ensure date as string will be computed
            keep_default_dates=True,  # Ensure columns with specified name will be computed as date.
            convert_axes=False,
        ).replace("NaN", np.nan)

    raise ValueError(f"unsupported content_type {content_type}")


load_parquet = partial(load_df, content_type=MimeTypes.PARQUET)


def dump_df(df: pd.DataFrame, content_type: MimeType, orient: JSONOrient | None = None) -> bytes | str:
    if content_type == MimeTypes.PARQUET:
        try:
            return df.to_parquet(None, index=True, engine="pyarrow")
        except ValueError as e:
            # possible for V0 storage case when column values are not string, so let's use direct serialisation
            columns_type = df.columns.inferred_type
            get_logger().error(f"dataframe to parquet error: {e}, columns inferred type = {columns_type}, trying v0")
            if columns_type == "string":
                # if columns are string it's a different error so immediately raise
                raise ValueError("invalid data format") from e
            return to_parquet_v0(df)

    if content_type == MimeTypes.JSON:
        # pandas' ``to_json`` defaults ``double_precision`` to 10, which silently
        # truncates float64 values that carry more than 10 digits after the decimal
        # point (curve values are stored as float64 and stay bit-exact in Parquet,
        # so the truncation only affects the JSON response). We raise the default
        # to the pandas maximum of 15 so JSON responses preserve as much precision
        # as pandas' JSON writer allows.
        return df.fillna("NaN").to_json(
            orient=(orient or JSONOrient.Split).value,
            index=True,
            date_format="iso",
            double_precision=15,
        )

    raise ValueError(f"unsupported content_type {content_type}")


dump_to_parquet = partial(dump_df, content_type=MimeTypes.PARQUET, orient=None)


def to_parquet_v0(df: pd.DataFrame) -> bytes:
    # wdms v0 to parquet way, unlike pandas.to_parquet it allows columns values to be numerical. To be used only for
    # backward compatibility reasons
    buffer = BytesIO()
    pq.write_table(
        Table.from_pandas(df, preserve_index=True),
        buffer,
        version="2.6",
        compression="snappy",
    )
    buffer.seek(0)
    return buffer.read()


def basic_describe(df: pd.DataFrame, reference_name: str | None) -> DataframeBasicDescribe:
    """
    Construct `DataframeBasicDescribe` object from a dataframe.
    :param df:
    :param reference_name: column name to use as reference, if `None` or not in the dataframe, the index will be used
                            instead with the name "_wdms_index_"
    :return: object describe constructed
    """
    grouped_curves = group_curve_columns(df.columns, include_non_array=True)
    curves = {label: len(columns) for label, columns in grouped_curves.items()}
    reference = ColumnDescribe.from_column(df, reference_name) if reference_name else ColumnDescribe.from_index(df)
    return DataframeBasicDescribe(
        rowCount=len(df.index),
        curves=curves,
        reference=reference,
    )


def filter_by_index(df: pd.DataFrame, offset: int | None = None, limit: int | None = None) -> pd.DataFrame:
    """select range"""
    if offset and limit:
        return df.iloc[offset : offset + limit]
    if offset:
        return df.iloc[offset:]
    if limit:
        return df.iloc[:limit]
    return df


def split_into_chunks(
    df: pd.DataFrame,
    *,
    max_values_per_chunk: int,
    max_columns_per_chunk: int,
) -> List[pd.DataFrame]:
    """
    breakdown a dataframe into several chunks given the limits of total number of values and columns provided. Split is
    down column first. It applies horizontal slicing (by row) only if single column contains more values then the limit
    requested.
    :param df: dataframe to chunk
    :param max_values_per_chunk: maximum number of values in each chunk
    :param max_columns_per_chunk: maximum number of column in each chunk
    :return: list of dataframe/chunk
    """
    if df.empty:
        return [df]

    nb_rows = len(df)
    columns = natsorted(df.columns.tolist())

    chunks: List[pd.DataFrame] = []
    # split column first
    if nb_rows > max_values_per_chunk:
        for c in columns:
            single_column_df = df[[c]]
            for i in range(0, nb_rows, max_values_per_chunk):
                chunks.append(single_column_df.iloc[i : i + max_values_per_chunk])
    else:
        column_per_chunk = min(max_columns_per_chunk, int(max_values_per_chunk / nb_rows))
        for i in range(0, len(columns), column_per_chunk):
            chunks.append(df[columns[i : i + column_per_chunk]])
    return chunks
