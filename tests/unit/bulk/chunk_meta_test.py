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

import pytest
from ..generate_data import generate_df, generate_date_range
from wdmsworker.bulk.chunk_meta import ChunkMeta, find_conflicts


@pytest.mark.parametrize("index", [[1, 2], [0.5, 1.5], generate_date_range(2)])
@pytest.mark.parametrize("col1", ["int1", "float1", "bool1", "date1"])
@pytest.mark.parametrize("col2", ["int1", "float1", "bool1", "date1"])
def test_dump_then_reload(index, col1, col2):
    df = generate_df([col1, col2], index)
    initial_meta = ChunkMeta.from_dataframe("base_dir/fakeindexhash.fakecolhash.meta", df)
    reloaded_meta = ChunkMeta.load("base_dir/fakeindexhash.fakecolhash.meta", initial_meta.dump())
    assert initial_meta.__dict__ == reloaded_meta.__dict__


def test_from_dataframe():
    meta = ChunkMeta.from_dataframe(
        "base_dir/fakeindexhash.fakecolhash.meta", generate_df(["col1", "floatcol2"], [1, 2, 4])
    )
    assert meta.filename == "fakeindexhash.fakecolhash.meta"
    assert meta.filepath == "base_dir/fakeindexhash.fakecolhash.meta"
    assert meta.index_hash == "fakeindexhash"
    assert meta.column_hash == "fakecolhash"
    assert meta.columns == ["col1", "floatcol2"]
    assert "int" in meta.dtypes[0]
    assert "float" in meta.dtypes[1]
    assert "int" in meta.index_dtype
    assert meta.index_start == 1
    assert meta.index_end == 4
    assert meta.nb_rows == 3


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
    ],
)
def test_overlap(cols_left, idx_range_left, cols_right, idx_range_right, col_overlap, idx_overlap):
    other_args = {"filepath": "fakeindexhash.fakecolhash.meta", "dtypes": [], "index_dtype": "any", "nb_rows": 3}

    # for increasing idx
    ch_left = ChunkMeta(columns=cols_left, index_start=idx_range_left[0], index_end=idx_range_left[1], **other_args)
    ch_right = ChunkMeta(columns=cols_right, index_start=idx_range_right[0], index_end=idx_range_right[1], **other_args)

    assert ch_left.share_columns_with(ch_right) == col_overlap
    assert ch_left.index_overlap_with(ch_right) == idx_overlap
    assert ch_left.overlap_with(ch_right) == (idx_overlap and col_overlap)

    # for decreasing idx
    ch_left = ChunkMeta(columns=cols_left, index_start=idx_range_left[1], index_end=idx_range_left[0], **other_args)
    ch_right = ChunkMeta(columns=cols_right, index_start=idx_range_right[1], index_end=idx_range_right[0], **other_args)

    assert ch_left.share_columns_with(ch_right) == col_overlap
    assert ch_left.index_overlap_with(ch_right) == idx_overlap
    assert ch_left.overlap_with(ch_right) == (idx_overlap and col_overlap)


@pytest.mark.perf
def test_find_conflicts_perf():
    # ensure can handle many chunk to find conflict, here test 2000+ chunks

    import datetime

    ch = [
        ChunkMeta(f"{i}.c.meta", [f"C{i}[{j}]" for j in range(500)], [], "int32", i * 5, i * 5 + 4, 4)
        for i in range(2000)  # i*5
    ]

    # add conflicting chunk (2000) against chunk 0 and 10
    ch.append(ChunkMeta(f"2000.c.meta", ["C0[30]", "C10[36]"], [], "int32", 3, 100, 4))

    # add conflicting chunk (2001) against chunk 2
    ch.append(ChunkMeta(f"2001.c.meta", ["C2[30]", "C2[36]"], [], "int32", 3, 11, 4))

    ts = datetime.datetime.now()
    result = find_conflicts(ch)
    print("took ", (datetime.datetime.now() - ts).total_seconds())

    # using filename to check result, use dict with len as key since order not guarantee
    expected = {
        3: {"2000.c.meta", "0.c.meta", "10.c.meta"},
        2: {"2001.c.meta", "2.c.meta"},
    }
    actual = {len(group): {ch.filename for ch in group} for group in result}

    assert actual == expected
