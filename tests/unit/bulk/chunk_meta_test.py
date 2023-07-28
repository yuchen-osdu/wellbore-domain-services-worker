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
import pandas as pd
import pytest
import numpy as np

from wdmsworker.bulk.chunk_meta import ChunkMeta, sort_chunk_metas_by_index
from wdmsworker.bulk.errors import BulkValidationError

from ..generate_data import generate_df, generate_date_range, generate_df_dtype


@pytest.mark.parametrize("index", [[1, 2, 3], [0.5, 1.5, 2.0], generate_date_range(3)])
@pytest.mark.parametrize("col1", ["int1", "float1", "bool1", "date1"])
@pytest.mark.parametrize(
    "reference", [(None, None), ([1, 4, 5], "increasing"), ([9.1, 9.0, 8.9], "decreasing"), ([2.2, 8.8, 5.5], None)]
)
def test_dump_then_reload(index, col1, reference):
    ref_values, ref_monotonicity = reference
    df = generate_df([col1], index)
    if ref_values:
        df["MD"] = ref_values
    expected_meta = ChunkMeta.from_dataframe(df, reference_curve="MD" if ref_values else None)

    reloaded_meta = ChunkMeta.load(expected_meta.filename_with_extension, expected_meta.dump())
    assert expected_meta.origin == ChunkMeta.Origin.DATAFRAME
    assert reloaded_meta.origin == ChunkMeta.Origin.META_V2

    expected_meta.origin = ChunkMeta.Origin.META_V2
    assert expected_meta.__dict__ == reloaded_meta.__dict__


def test_load_previous_version_chunk_meta():
    content = (
        b'{"columns": ["MD", "X"], "dtypes": ["int64", "int64"], "nb_rows": 15, "index_hash":'
        b' "fc0bb6fa34e09e11be9334895f164c90aa98afb6"}'
    )
    session_path = "session/1a5107c7-d7db-482c-9854-eff3b084a58f/data"
    chunk_filename = "5_19_1688039802126.c16557b6759c501f396c2822b8abfca92dc777f3.meta"
    meta = ChunkMeta.load(f"{session_path}/{chunk_filename}", content)
    assert meta.origin == ChunkMeta.Origin.META_V1
    assert meta.base_path == session_path
    assert meta.get_filename(ChunkMeta.FileType.META) == chunk_filename
    assert meta.columns == ["MD", "X"]
    assert meta.nb_rows == 15
    assert meta.index.end == 19
    assert meta.index.start == 5
    assert "int" in meta.index.dtype
    assert meta.index_hash == "fc0bb6fa34e09e11be9334895f164c90aa98afb6"
    assert meta.column_hash == "c16557b6759c501f396c2822b8abfca92dc777f3"


def test_from_dataframe():
    df = generate_df(["col1", "floatcol2"], [1, 2, 4])
    meta = ChunkMeta.from_dataframe(df)
    assert meta.filename == ChunkMeta.generate_filename(df)
    assert meta.index_hash in meta.filename
    assert meta.column_hash in meta.filename
    assert meta.columns == ["col1", "floatcol2"]
    assert "int" in meta.index.dtype
    assert meta.index.start == 1
    assert meta.index.end == 4
    assert meta.nb_rows == 3
    assert "int" in meta.column_dtypes["col1"]
    assert "float" in meta.column_dtypes["floatcol2"]


@pytest.mark.parametrize(
    "cols_left, idx_range_left, cols_right, idx_range_right, col_overlap, idx_overlap",
    [
        (["A", "B"], [1, 3], ["D", "C"], [4, 5], False, False),
        (["A", "B"], [1.1, 3.33333333], ["D", "C"], [3.3333333301, 5], False, False),
        # column overlap
        (["A", "B"], [1, 3], ["B", "C"], [4, 5], True, False),
        # idx overlap cases
        (["A", "B"], [1, 3], ["D", "C"], [3, 5], False, True),
        (["A", "B"], [1, 3], ["D", "C"], [2, 5], False, True),
        (["A", "B"], [1, 3], ["D", "C"], [0, 5], False, True),
        (["A", "B"], [1, 3], ["D", "C"], [0, 2], False, True),
        (["A", "B"], [1, 3], ["D", "C"], [0, 1], False, True),
        (["A", "B"], [1.1, 3.0], ["D", "C"], [3.0, 5.0], False, True),
        (["A", "B"], [1.1, 3.0], ["D", "C"], [2.0, 5.0], False, True),
        (["A", "B"], [1.1, 3.0], ["D", "C"], [0.0, 5.0], False, True),
        (["A", "B"], [1.1, 3.0], ["D", "C"], [0.0, 2.0], False, True),
        (["A", "B"], [1.1, 3.0], ["D", "C"], [0.0, 1.1], False, True),
        # both column and idx
        (["A", "B"], [1, 9], ["A", "C"], [3, 5], True, True),
        # single row
        (["A", "B"], [1], ["C", "A"], [1], True, True),
        (["A", "B"], [1], ["C", "A"], [0, 1], True, True),
        (["A", "B"], [1], ["C"], [1], False, True),
    ],
)
def test_overlap(cols_left, idx_range_left, cols_right, idx_range_right, col_overlap, idx_overlap):
    other_args = {
        "filepath": "ih.ch.meta",
        "columns_hash": "ch",
        "index_hash": "ih",
        "nb_rows": 3,
        "dtypes": ["int"],
    }

    # for increasing idx
    ch_left = ChunkMeta(
        columns=cols_left,
        index_start_end=ChunkMeta.ColumnStartEndValues("", idx_range_left[0], idx_range_left[-1], "any"),
        **other_args,
    )
    ch_right = ChunkMeta(
        columns=cols_right,
        index_start_end=ChunkMeta.ColumnStartEndValues("", idx_range_right[0], idx_range_right[-1], "any"),
        **other_args,
    )

    assert ch_left.share_columns_with(ch_right) == col_overlap
    assert ch_left.index_overlap_with(ch_right) == idx_overlap
    assert ch_left.overlap_with(ch_right) == (idx_overlap and col_overlap)

    # for decreasing idx
    ch_left = ChunkMeta(
        columns=cols_left,
        index_start_end=ChunkMeta.ColumnStartEndValues("", idx_range_left[-1], idx_range_left[0], "any"),
        **other_args,
    )
    ch_right = ChunkMeta(
        columns=cols_right,
        index_start_end=ChunkMeta.ColumnStartEndValues("", idx_range_right[-1], idx_range_right[0], "any"),
        **other_args,
    )

    assert ch_left.share_columns_with(ch_right) == col_overlap
    assert ch_left.index_overlap_with(ch_right) == idx_overlap
    assert ch_left.overlap_with(ch_right) == (idx_overlap and col_overlap)


def test_should_generate_same_chunk_filename():
    df_abc1 = generate_df_dtype({"A": "float", "B": "float", "C": "int"}, [0, 1, 2])
    df_abc2 = generate_df_dtype({"A": "float", "B": "float", "C": "int"}, [0, 1, 2])

    # same dataframe produces same name
    assert ChunkMeta.generate_filename(df_abc1) == ChunkMeta.generate_filename(df_abc2)

    # column order doesn't matter
    df_acb = generate_df_dtype({"A": "float", "C": "int", "B": "float"}, [0, 1, 2])
    assert ChunkMeta.generate_filename(df_abc1) == ChunkMeta.generate_filename(df_acb)


def test_should_generate_different_chunk_filename():
    df_ref = generate_df_dtype({"A": "float", "B": "float", "C": "int"}, [0, 1, 2])

    # change columns
    assert ChunkMeta.generate_filename(df_ref) != ChunkMeta.generate_filename(
        generate_df_dtype({"A": "float", "C": "int"}, [0, 1, 2])
    )

    # change index edges
    assert ChunkMeta.generate_filename(df_ref) != ChunkMeta.generate_filename(
        generate_df_dtype({"A": "float", "B": "float", "C": "int"}, [1, 2])
    )
    assert ChunkMeta.generate_filename(df_ref) != ChunkMeta.generate_filename(
        generate_df_dtype({"A": "float", "B": "float", "C": "int"}, [0, 1])
    )

    # length of index different
    assert ChunkMeta.generate_filename(df_ref) != ChunkMeta.generate_filename(
        generate_df_dtype({"A": "float", "C": "int", "B": "float"}, [0, 2])
    )


def test_sort_chunk_metas_by_index_increasing():
    df1 = ChunkMeta.from_dataframe(generate_df_dtype({"A": "float"}, [5]))
    df2 = ChunkMeta.from_dataframe(generate_df_dtype({"A": "float"}, [6, 9]))
    df3 = ChunkMeta.from_dataframe(generate_df_dtype({"A": "float"}, [0, 1, 2]))

    ordered_chunks = sort_chunk_metas_by_index([df1, df2, df3])
    assert len(ordered_chunks) == 3
    assert [df3.filename, df1.filename, df2.filename] == [m.filename for m in ordered_chunks]

    df2 = ChunkMeta.from_dataframe(generate_df_dtype({"A": "float"}, [6]))
    df3 = ChunkMeta.from_dataframe(generate_df_dtype({"A": "float"}, [0]))

    # by convention, single row chunk are increasing
    ordered_chunks = sort_chunk_metas_by_index([df1, df2, df3])
    assert len(ordered_chunks) == 3
    assert [df3.filename, df1.filename, df2.filename] == [m.filename for m in ordered_chunks]

    assert sort_chunk_metas_by_index([df3]) == [df3]
    assert sort_chunk_metas_by_index([]) == []


def test_sort_chunk_metas_by_index_decreasing():
    df1 = ChunkMeta.from_dataframe(generate_df_dtype({"A": "float"}, [0]))
    df2 = ChunkMeta.from_dataframe(generate_df_dtype({"A": "float"}, [9, 6]))
    df3 = ChunkMeta.from_dataframe(generate_df_dtype({"A": "float"}, [2, 1]))

    ordered_chunks = sort_chunk_metas_by_index([df1, df2, df3])
    assert len(ordered_chunks) == 3
    assert [df2.filename, df3.filename, df1.filename] == [m.filename for m in ordered_chunks]


def test_sort_chunk_metas_by_index_raise_heterogeneous_order():
    df1 = ChunkMeta.from_dataframe(generate_df_dtype({"A": "float"}, [5, 6]))
    df2 = ChunkMeta.from_dataframe(generate_df_dtype({"A": "float"}, [9, 8, 7]))
    df3 = ChunkMeta.from_dataframe(generate_df_dtype({"A": "float"}, [0, 1, 2]))

    with pytest.raises(BulkValidationError):
        sort_chunk_metas_by_index([df1, df2, df3])


def test_sort_then_make_df():
    df1 = ChunkMeta.from_dataframe(pd.DataFrame({"A": [3.0]}, index=[5]), reference_curve="A")
    df2 = ChunkMeta.from_dataframe(pd.DataFrame({"A": [4.0, 4.1, 4.2, 5.0]}, index=[8, 9, 10, 11]), reference_curve="A")
    df3 = ChunkMeta.from_dataframe(pd.DataFrame({"A": [1.0, 1.2, 2.0]}, index=[0, 1, 2]), reference_curve="A")

    ordered_chunks = sort_chunk_metas_by_index([df1, df2, df3])
    df = pd.concat(m.start_end_df() for m in ordered_chunks)
    assert df["A"].values.tolist() == [1.0, 2.0, 3.0, 4.0, 5.0]


@pytest.fixture
def dataframe_many_columns() -> pd.DataFrame:
    size = 150_000
    return generate_df_dtype({f"A_{size - i}": "int" for i in range(size)}, [0, 1, 2])


@pytest.mark.perf
def test_perf_generate_filename(dataframe_many_columns):
    ChunkMeta.generate_filename(dataframe_many_columns)


def test_generate_chunk_filename_is_idempotent_any_run_machine_version():
    df = pd.DataFrame(
        {
            "c1": pd.Series([1.1, 2.2, 3.3], dtype=np.dtype("float64")),
            "c2": pd.Series([4.4, 5.5, 6.6], dtype=np.dtype("float64")),
        },
        index=range(6),
    )
    assert ChunkMeta.generate_filename(df) == "2LW7VFHRUDWX.NN67FK2YVFIG"
