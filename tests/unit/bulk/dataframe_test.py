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
import io

import pytest

# TODO [TAG pandas dependent]
import pandas as pd

from wdmsworker.model.json_orient import JSONOrient
from ..generate_data import generate_df
from wdmsworker.model.mime_types import MimeTypes
from wdmsworker.bulk.dataframe import (
    group_curve_columns,
    match_full_slice_pattern,
    get_array_columns,
    sort_column_labels,
    sort_dataframe_column,
    get_requested_columns,
    load_df,
    expand_columns,
    basic_describe,
    column_describe,
    get_row_count_and_columns,
    dump_df,
)

from wdmsworker.model.describe import DataframeBasicDescribe, ColumnBasicDescribe, ColumnExtendedDescribe


@pytest.mark.parametrize("columns", [["A", "B", "C"], [0, 1, 3], [0.0, 1.1, 7.1]])
def test_dump_parquet(columns):
    ref_df = generate_df(columns, range(10))
    content = io.BytesIO(dump_df(ref_df, MimeTypes.PARQUET))
    actual_df = pd.read_parquet(content)
    pd.testing.assert_frame_equal(ref_df, actual_df)


@pytest.mark.parametrize("columns", [["A", "B", "C"], [0, 1, 3], [0.0, 1.1, 7.1]])
def test_dump_json(columns):
    ref_df = generate_df(columns, range(10))
    # force dtype as int64, as generate_df may generate int32 data but will infer int64 for json
    for c in columns:
        ref_df[c] = ref_df[c].astype("int64")
    content = io.StringIO(dump_df(ref_df, MimeTypes.JSON))
    actual_df = pd.read_json(content, orient=JSONOrient.Split)
    pd.testing.assert_frame_equal(ref_df, actual_df)


def test_dump_invalid():
    with pytest.raises(ValueError):
        dump_df(generate_df([0], [0]), "invalid_mime")


@pytest.mark.parametrize(
    "column_labels, include_non_array, expected",
    [
        # empty should return empty
        ({}, True, {}),
        ({}, False, {}),
        # basic cases, non array excluded
        (
            ["A", "B", "C[0]", "C[1]", "D[0]", "D[1]", "D[2]"],
            False,
            {"C": ["C[0]", "C[1]"], "D": ["D[0]", "D[1]", "D[2]"]},
        ),
        (["A", "B", "C"], False, {}),
        # basic cases, non array included
        (
            ["A", "B", "C[0]", "C[1]", "D[0]", "D[1]", "D[2]"],
            True,
            {"A": ["A"], "B": ["B"], "C": ["C[0]", "C[1]"], "D": ["D[0]", "D[1]", "D[2]"]},
        ),
        (["A", "B", "C"], True, {"A": ["A"], "B": ["B"], "C": ["C"]}),
        # check order is reserved
        (["C[9]", "C[1]", "C[100]", "C[7]"], False, {"C": ["C[9]", "C[1]", "C[100]", "C[7]"]}),
    ],
)
def test_group_curve_columns_basic(column_labels, include_non_array, expected):
    assert group_curve_columns(column_labels, include_non_array) == expected
    if include_non_array:
        # ensure default contains non array curves
        assert group_curve_columns(column_labels) == expected
    else:
        # ensure get_array_columns filters out non array curves
        assert get_array_columns(column_labels) == expected


def test_expand_columns():
    assert expand_columns(["A", "B"]) == ["A", "B"]
    assert expand_columns(["A", "C[1:3]"]) == ["A", "C[1]", "C[2]", "C[3]"]


def test_group_curve_columns_include_non_array_by_default():
    assert "A" in group_curve_columns(["A", "B[0]", "B[1]"])


@pytest.mark.skip
@pytest.mark.slow
@pytest.mark.perf
def test_group_curve_columns_handle_one_million_columns():
    size = 1_000_000

    # one giant array
    r = group_curve_columns((f"C[{i}]" for i in range(size)), True)
    assert len(r["C"]) == size

    # many non array
    r = group_curve_columns((f"C{i}" for i in range(size)), True)
    assert len(r) == size

    # many big arrays
    r = group_curve_columns((f"C{j}[{i}]" for i in range(int(size / 1000)) for j in range(1000)), True)
    assert len(r) == 1000
    assert len(r["C500"]) == 1000


@pytest.mark.parametrize(
    "column_label, expected",
    [
        ("C[0:10]", ("C", "0", "10")),
        ("C", (None, None, None)),
        ("C[0]", (None, None, None)),
        ("C[0:]", (None, None, None)),
        ("C[:10]", (None, None, None)),
    ],
)
def test_match_full_slice_pattern(column_label, expected):
    assert match_full_slice_pattern(column_label) == expected


def test_sort_column_label():
    assert sort_column_labels(["A", "C[10]", "C[20]", "C[1]", "Z", "C[2]"]) == [
        "A",
        "C[1]",
        "C[2]",
        "C[10]",
        "C[20]",
        "Z",
    ]


def test_sort_dataframe_column():
    df = pd.DataFrame({"a": [1, 2], "z": [3, 4], "b": [5, 6]})
    assert list(df.columns) == ["a", "z", "b"]
    assert list(sort_dataframe_column(df).columns) == ["a", "b", "z"]


def test_select_columns():
    # basic example:
    assert get_requested_columns(["A", "C"], {"A", "B", "C", "D"}) == (["A", "C"], [], False)

    # with non matching selection:
    assert get_requested_columns(["A", "X"], {"A", "B", "C", "D"}) == (["A"], ["X"], False)

    # selection a curve array:
    assert get_requested_columns(["A"], {"A[0]", "A[1]", "A[2]", "D"}) == (["A[0]", "A[1]", "A[2]"], [], True)

    # array slicing
    assert get_requested_columns(["A[2:4]"], {"A[0]", "A[1]", "A[2]", "A[3]", "A[4]", "A[5]", "A[6]"}) == (
        ["A[2]", "A[3]", "A[4]"],
        [],
        True,
    )


def test_load_df():
    df = pd.DataFrame({"a": [1, 2], "z": [3, 4], "b": [5, None]})
    pq_content = df.to_parquet()
    json_content = df.to_json(orient="split")

    pd.testing.assert_frame_equal(df, load_df(pq_content, MimeTypes.PARQUET))
    pd.testing.assert_frame_equal(df, load_df(json_content, MimeTypes.JSON))


@pytest.mark.parametrize(
    "dataframe,expected",
    [
        (
            pd.DataFrame({"a": [1, 2], "z": [3, 4], "b": [5, None]}, index=pd.Index(range(3, 5), dtype="int64")),
            DataframeBasicDescribe(
                rowCount=2,
                columnCount=3,
                index=ColumnBasicDescribe(name="_wdms_index_", start="3", end="4", type="int64"),
                curves={"a": 1, "z": 1, "b": 1},
            ),
        ),
        (
            pd.DataFrame({"a[0]": [1], "a[2]": [3]}, index=pd.Index([3.3], dtype="float64")),
            DataframeBasicDescribe(
                rowCount=1,
                columnCount=2,
                index=ColumnBasicDescribe(name="_wdms_index_", start="3.3", end="3.3", type="float64"),
                curves={"a": 2},
            ),
        ),
        (
            pd.DataFrame({"a": [1, 2, 3], "z": [3, 4, 5]}, index=pd.Index(["a", "b", "c"])),
            DataframeBasicDescribe(
                rowCount=3,
                columnCount=2,
                index=ColumnBasicDescribe(name="_wdms_index_", start="a", end="c", type="object"),
                curves={"a": 1, "z": 1},
            ),
        ),
        (pd.DataFrame(), DataframeBasicDescribe(rowCount=0, columnCount=0, curves={})),
    ],
)
def test_basic_describe(dataframe, expected):
    assert basic_describe(dataframe) == expected


@pytest.mark.parametrize(
    "dataframe,expected",
    [
        (
            pd.DataFrame({"a": [1, 2, 4]}),
            ColumnExtendedDescribe(
                name="a",
                start="1",
                end="4",
                type="int64",
                hasDuplicate=False,
                order="ASC",
                hasNan=False,
            ),
        ),
        (
            pd.DataFrame({"a": [2.1, 1.2, -4.0]}),
            ColumnExtendedDescribe(
                name="a",
                start="2.1",
                end="-4.0",
                type="float64",
                hasDuplicate=False,
                order="DESC",
                hasNan=False,
            ),
        ),
        (
            pd.DataFrame({"a": [1, 1, 4]}),
            ColumnExtendedDescribe(
                name="a",
                start="1",
                end="4",
                type="int64",
                hasDuplicate=True,
                order="ASC",
                hasNan=False,
            ),
        ),
        (
            pd.DataFrame({"a": [1.1, None, 4.7, None]}),
            ColumnExtendedDescribe(
                name="a",
                start="1.1",
                end="nan",
                type="float64",
                hasDuplicate=True,
                order=None,
                hasNan=True,
            ),
        ),
    ],
)
def test_column_describe(dataframe, expected):
    assert column_describe(dataframe, "a") == expected


def test_column_describe_invalid_cases():
    with pytest.raises(ValueError):
        column_describe(pd.DataFrame({"a": range(3)}), "c")

    with pytest.raises(ValueError):
        column_describe(pd.DataFrame({"a": []}), "a")


@pytest.mark.parametrize(
    "df, expected_result",
    [
        ({"col1": [1, 2, 3], "col2": [4, 5, 6]}, (3, ["col1", "col2"])),
        (None, (0, [])),
    ],
)
def test_get_row_count_and_columns(df, expected_result):
    # Create a test DataFrame
    test_df = pd.DataFrame(df)

    # Call the function and store the result
    result = get_row_count_and_columns(test_df)

    # Assert that the result is a tuple containing the expected number of rows and columns
    assert result == expected_result
