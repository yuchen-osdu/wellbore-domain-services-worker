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

"""
Module dataframe manipulation functions
"""

import re
from contextlib import suppress
from typing import Iterable, Dict, List, Tuple, Optional, Set
from io import BytesIO

from natsort import natsorted

# TODO [TAG pandas dependent]
import pandas as pd
import numpy as np
import pyarrow.parquet as pq
from pyarrow import Table

from ..model.json_orient import JSONOrient
from ..model.mime_types import MimeType, MimeTypes
from ..model.describe import DataframeBasicDescribe, ColumnDescribe
from ..logger import get_logger

re_column_array = re.compile(r"^(?P<name>.+)\[(?P<start>[^:]+):?(?P<stop>.*)\]$")


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
                f"{curve_name_slice}[{i}]" for i in range(int(slice_start), int(slice_stop) + 1)  # type: ignore
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


# TODO [TAG pandas dependent]
def reorder_dataframe_columns(df: pd.DataFrame, curve_selection: List[str] | None) -> pd.DataFrame:
    """Reorder dataframe columns order according curve_selection if reordering is necessary"""
    if curve_selection and list(curve_selection) != df.columns.tolist():
        return df[curve_selection]

    return df


# TODO [TAG pandas dependent]
def sort_dataframe_column(df: pd.DataFrame) -> pd.DataFrame:
    """Apply natural sorting on dataframe columns"""
    sorted_columns = sort_column_labels(df.columns)
    return reorder_dataframe_columns(df, sorted_columns)


# TODO [TAG pandas dependent]
def load_df(file_like_data, content_type: MimeType) -> pd.DataFrame:
    if isinstance(file_like_data, bytes):
        file_like_data = BytesIO(file_like_data)

    if content_type == MimeTypes.PARQUET:
        return pd.read_parquet(file_like_data)
    elif content_type == MimeTypes.JSON:
        return pd.read_json(path_or_buf=file_like_data, orient="split", convert_axes=False).replace("NaN", np.NaN)

    raise ValueError(f"unsupported content_type {content_type}")


# TODO [TAG pandas dependent]
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
        return df.fillna("NaN").to_json(orient=(orient or JSONOrient.Split).value, index=True, date_format="iso")

    raise ValueError(f"unsupported content_type {content_type}")


# TODO [TAG pandas dependent]
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


# TODO [TAG pandas dependent]
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


# TODO [TAG pandas dependent]
def filter_by_index(df: pd.DataFrame, offset: int | None = None, limit: int | None = None) -> pd.DataFrame:
    """select range"""
    if offset and limit:
        return df.iloc[offset : offset + limit]
    if offset:
        return df.iloc[offset:]
    if limit:
        return df.iloc[:limit]
    return df


# TODO [TAG pandas dependent]
def get_row_count_and_columns(df: pd.DataFrame) -> Tuple[int, List[str]]:
    """
    Extract from the data frame the number of rows and list of columns of the bulk data
    :param df: The input DataFrame
    :return: The number of rows and the list of columns
    """
    nb_row = len(df.index)
    columns = df.columns.tolist()
    return nb_row, columns
