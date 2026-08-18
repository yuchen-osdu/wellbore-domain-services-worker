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
from functools import reduce
from datetime import datetime

import pytest

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
    dump_df,
    split_into_chunks,
    columns_to_slices,
)

from wdmsworker.model.describe import DataframeBasicDescribe, ColumnDescribe


def test_columns_to_slices():
    assert {"A", "C[1:6]"} == set(columns_to_slices(["A", "C[1]", "C[4]", "C[3]", "C[2]", "C[2]", "C[6]"]))
    assert {"A", "C[1]", "C[4]", "C[3]", "C[8]", "C[2]", "C[6]"} == set(
        columns_to_slices(["A", "C[1]", "C[4]", "C[3]", "C[8]", "C[2]", "C[6]"])
    )


@pytest.mark.parametrize("columns", [["A", "B", "C"], [0, 1, 3], [0.0, 1.1, 7.1]])
def test_dump_json(columns):
    ref_df = generate_df(columns, range(10))
    # force dtype as int64, as generate_df may generate int32 data but will infer int64 for json
    for c in columns:
        ref_df[c] = ref_df[c].astype("int64")
    content = io.StringIO(dump_df(ref_df, MimeTypes.JSON))
    actual_df = pd.read_json(content, orient=JSONOrient.Split)
    pd.testing.assert_frame_equal(ref_df, actual_df)


# Regression: pandas' to_json defaults to double_precision=10, which silently
# truncates float64 values with more than 10 digits after the decimal point.
# dump_df must default to double_precision=15 (pandas maximum) so JSON responses
# do not truncate stored curve values.
@pytest.mark.parametrize(
    "value",
    [555.9800101010101, 10.910000000007, 23735.910000000007],
)
def test_dump_json_preserves_float_precision(value):
    import json

    df = pd.DataFrame({"GR": [value]}, index=[0])

    result = dump_df(df, MimeTypes.JSON)

    parsed = json.loads(result)
    assert parsed["data"][0][0] == value


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


# @pytest.mark.skip
@pytest.mark.slow
@pytest.mark.perf
def test_columns_to_slides_handle_many_columns():
    size = 300_000

    # one array
    columns = (f"C[{i}]" for i in range(size))
    ts = datetime.now()
    columns_to_slices(columns)
    print("single array columns to slices took ", (datetime.now() - ts).total_seconds())

    # many columns no array
    columns = (f"C{i}" for i in range(size))
    ts = datetime.now()
    columns_to_slices(columns)
    print("no array many columns to slices took ", (datetime.now() - ts).total_seconds())

    # one array split into 500 columns chunks
    columns_list = [[f"C[{i}]" for i in range(start, start + 500)] for start in range(0, size, 500)]
    ts = datetime.now()
    for columns in columns_list:
        columns_to_slices(columns)
    print("one array, several chunks columns to slices took ", (datetime.now() - ts).total_seconds())


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

    # non existing slicing
    assert get_requested_columns(["A[5:7]"], {"A[0]", "A[1]", "A[2]", "A[3]", "A[4]", "A[5]", "A[6]"}) == (
        [],
        ["A[7]"],
        True,
    )

    # non existing slicing, full outbound slice
    _, non_existing, _ = get_requested_columns(["A[50:51]"], {"A[0]", "A[1]", "A[2]", "A[3]", "A[4]", "A[5]", "A[6]"})
    assert set(non_existing) == {"A[50]", "A[51]"}

    # non existing curve
    assert get_requested_columns(["A", "Z"], {"A", "B", "C", "D"}) == (["A"], ["Z"], False)


def test_load_df():
    df = pd.DataFrame(
        {
            "int-A": 621,
            "float-B": 10.00,
            "bool-D": True,
            "date": "1640995200000modified",
            "2022-01-01T08:08:08 +02:00string-G": "string_value_0",
        },
        index=range(1),
    )

    pq_content = df.to_parquet()
    json_content = df.to_json(orient="split", date_format="iso")

    pd.testing.assert_frame_equal(df, load_df(pq_content, MimeTypes.PARQUET))
    pd.testing.assert_frame_equal(df, load_df(json_content, MimeTypes.JSON))


@pytest.mark.parametrize(
    "dataframe,ref_name,expected",
    [
        (
            pd.DataFrame({"a": [1, 2], "z": [3, 4], "b": [5, None]}, index=pd.Index(range(3, 5))),
            None,
            DataframeBasicDescribe(
                rowCount=2,
                curves={"a": 1, "z": 1, "b": 1},
                reference=ColumnDescribe(
                    name="_wdms_index_",
                    startEnd=pd.DataFrame({"_wdms_index_": [3, 4]}, index=[3, 4]).to_dict("split"),
                    monotonicity="increasing",
                    hasDuplicate=False,
                    hasNan=False,
                    dataType="int64",
                ),
            ),
        ),
        (
            pd.DataFrame({"a[0]": [1], "a[2]": [3]}, index=pd.Index([3.3])),
            None,
            DataframeBasicDescribe(
                rowCount=1,
                curves={"a": 2},
                reference=ColumnDescribe(
                    name="_wdms_index_",
                    startEnd=pd.DataFrame({"_wdms_index_": [3.3]}, index=[3.3]).to_dict("split"),
                    monotonicity="increasing",
                    hasDuplicate=False,
                    hasNan=False,
                    dataType="float64",
                ),
            ),
        ),
        (
            pd.DataFrame({"a": [1, 2, 3], "z": [3, 4, 5]}, index=pd.Index(["a", "b", "c"])),
            None,
            DataframeBasicDescribe(
                rowCount=3,
                curves={"a": 1, "z": 1},
                reference=ColumnDescribe(
                    name="_wdms_index_",
                    startEnd=pd.DataFrame({"_wdms_index_": ["a", "c"]}, index=pd.Index(["a", "c"])).to_dict("split"),
                    monotonicity="increasing",
                    hasDuplicate=False,
                    hasNan=False,
                    dataType="object",
                ),
            ),
        ),
        (
            pd.DataFrame({"a": [1.1, None, 1.1], "z": [5, 4, 1]}, index=pd.Index([3, 2, 1])),
            "z",
            DataframeBasicDescribe(
                rowCount=3,
                curves={"a": 1, "z": 1},
                reference=ColumnDescribe(
                    name="z",
                    startEnd=pd.DataFrame({"z": [5, 1]}, index=pd.Index([3, 1])).to_dict("split"),
                    monotonicity="decreasing",
                    hasDuplicate=False,
                    hasNan=False,
                    dataType="int64",
                ),
            ),
        ),
        (
            pd.DataFrame({"a": [1.1, None, 1.1], "z": [3, 4, 5]}, index=pd.Index([3, 2, 1])),
            "a",
            DataframeBasicDescribe(
                rowCount=3,
                curves={"a": 1, "z": 1},
                reference=ColumnDescribe(
                    name="a",
                    startEnd=pd.DataFrame({"a": [1.1, 1.1]}, index=pd.Index([3, 1])).to_dict("split"),
                    monotonicity=None,
                    hasDuplicate=True,
                    hasNan=True,
                    dataType="float64",
                ),
            ),
        ),
    ],
)
def test_basic_describe(dataframe, ref_name, expected):
    actual = basic_describe(dataframe, ref_name)
    assert actual == expected


def test_basic_describe_unknown_column():
    df = generate_df(["GR", "DEN"], range(5))
    desc = basic_describe(df, "MD")
    assert not desc.reference.start_end_df().empty
    assert "MD" not in desc.reference.start_end_df()
    assert desc.reference.name != "MD"


def test_basic_describe_on_empty():
    desc = basic_describe(pd.DataFrame(), "MD")
    assert desc.curves == {}
    assert desc.rowCount == 0
    assert desc.reference.start_end_df().empty


@pytest.mark.parametrize(
    "nb_rows,nb_cols,max_chunk_values,max_chunk_cols",
    [
        [4, 4, 20, 4],  # no split needed
        [4, 4, 12, 4],  # split on columns because max values
        [14, 4, 12, 2],  # split on row because single columns contains more than max
    ],
)
def test_split_into_chunks(nb_rows, nb_cols, max_chunk_values, max_chunk_cols):
    reference_df = generate_df([f"float_{i}" for i in range(nb_cols)], index=range(nb_rows))
    dfs = split_into_chunks(reference_df, max_values_per_chunk=max_chunk_values, max_columns_per_chunk=max_chunk_cols)

    for df in dfs:
        assert len(df.columns) <= max_chunk_cols
        assert df.size <= max_chunk_values

        # ensure it always columns first cut
        # so cut on row only occurs if on single column too big
        if max_chunk_values >= nb_rows:
            assert len(df) == nb_rows

    # reconstruct
    actual_df = reduce(lambda acc, d: acc.combine_first(d), dfs)
    actual_df = actual_df[reference_df.columns.tolist()]  # reorder columns as previous reconstruct do not preserve it

    pd.testing.assert_frame_equal(reference_df, actual_df)


def test_split_into_chunks_empty_dataframe():
    df = pd.DataFrame()
    chunks = split_into_chunks(df, max_values_per_chunk=4, max_columns_per_chunk=5)
    assert chunks == [df]

    df = pd.DataFrame({"a": [], "b": []})
    chunks = split_into_chunks(df, max_values_per_chunk=4, max_columns_per_chunk=5)
    assert chunks == [df]
