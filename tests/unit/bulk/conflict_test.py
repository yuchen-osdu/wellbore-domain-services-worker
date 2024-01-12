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

import pandas as pd
import pytest

from osdu.core.api.storage.blob_storage_base import BlobStorageBase

from wdmsworker.bulk.chunk_meta import ChunkMeta
from wdmsworker.bulk.errors import BulkValidationError
from wdmsworker.bulk.conflict import resolve_single_conflict_group, find_conflicts

from ..generate_data import generate_df

conflicting_cases = [
    # ------------ conflicting cases ----------------
    #
    # first are previous chunks, which not much not conflict each other
    # second are chunks in session than are meant to update previous ones
    # third is the type of conflict but only within current chunks
    #  all chunks are in conflict, because columns are misaligned, i.e. chunks that contains A and B do not all
    # share the very same columns. In the two first it's AB, in the last ABC.
    [
        [],
        [
            (["A", "B"], 0, 2),
            (["A", "B"], 3, 4),
            (["A", "B", "C"], 5, 8),
        ],
        ["misaligned"],
    ],
    #  all chunks are in conflict due to transient conflict, `AB` conflicts with `BC`, `BC` with `CD`
    [
        [],
        [
            (["A", "B"], 0, 2),
            (["B", "C"], 3, 4),
            (["C", "D"], 5, 8),
        ],
        ["misaligned"],
    ],
    #  `ab` chunks conflicts due to index overlap, `bc` with `c` because of column alignment, no conflict on `xz`
    [
        [],
        [
            (["a", "b"], 0, 2),
            (["a", "b"], 1, 4),
            (["x", "z"], 5, 8),
            (["d", "c"], 3, 4),
            (["c"], 5, 8),
        ],
        ["misaligned", "overlap"],
    ],
    # `ab` conflicts with `bc` because of overlap and `c` for misalignment
    [
        [],
        [
            (["a", "b"], 0, 2),
            (["c", "b"], 1, 4),
            (["x", "z"], 5, 8),
            (["c"], 5, 8),
        ],
        ["misaligned", "overlap"],
    ],
    # ----- with previous bulk
    [
        [
            (["A", "B", "C"], 5, 8),
        ],
        [
            (["A", "B"], 0, 2),
            (["A", "B"], 3, 4),
        ],
        [],
    ],
    [
        [
            (["A"], 5, 8),
            (["B", "C"], 5, 8),
        ],
        [
            (["A", "B"], 0, 2),
            (["A", "B"], 3, 4),
        ],
        [],
    ],
    [
        [
            (["A", "B", "C"], 1, 3),
            (["A", "B", "C"], 5, 6),
            (["A", "B", "C"], 7, 8),
        ],
        [
            (["A", "Z"], 0, 2),
            (["A", "Z"], 3, 4),
        ],
        [],
    ],
    [
        [
            (["A", "B", "C"], 1, 3),
            (["A", "B", "C"], 4, 6),
            (["A", "B", "C"], 7, 8),
        ],
        [
            (["A", "x"], 0, 2),
            (["B", "y"], 3, 4),
            (["C", "z"], 3, 8),
        ],
        [],
    ],
    [  # Verify TooManyValues is not raised
        [
            (["A"], 0, 5),
        ],
        [
            (["A"], 5, 10_000_005),
        ],
        [],
    ],
]


async def make_and_store(bulk_storage_mock: BlobStorageBase, test_tenant, columns, start, end):
    df = generate_df(columns, range(start, end))
    ch = ChunkMeta.from_dataframe(df)
    await bulk_storage_mock.upload(test_tenant, ch.get_filepath(ChunkMeta.FileType.CHUNK), df.to_parquet())
    return df, ch


@pytest.mark.anyio
@pytest.mark.parametrize("previous_chunks,current_chunks,current_chunks_conflict_types", conflicting_cases)
async def test_resolve(
    bulk_storage_mock: BlobStorageBase,
    test_tenant,
    previous_chunks,
    current_chunks,
    current_chunks_conflict_types,  # conflict types only on current chunks
):
    async def store_and_combine(chunks):
        metas = []
        combined_df = pd.DataFrame()
        for chunk in chunks:
            df, meta = await make_and_store(bulk_storage_mock, test_tenant, *chunk)
            combined_df = combined_df.combine_first(df)
            metas.append(meta)
        return metas, combined_df

    previous_metas, previous_df = await store_and_combine(previous_chunks)
    current_metas, current_df = await store_and_combine(current_chunks)

    expected_df = current_df.combine_first(previous_df)

    resolved_chunk_meta = await resolve_single_conflict_group(
        bulk_storage_mock, test_tenant, "record_id", "session_id", current_metas, previous_metas
    )

    pds = []
    for chunk_meta in resolved_chunk_meta:
        content = await bulk_storage_mock.download(test_tenant, chunk_meta.get_filepath(ChunkMeta.FileType.CHUNK))
        pds.append(pd.read_parquet(BytesIO(content)))

    actual_df = pd.concat(pds)

    print(expected_df)
    print(actual_df)
    if "overlap" in current_chunks_conflict_types:
        if not actual_df.equals(expected_df):
            # because of index overlap there's no guarantee which one is first so which value be on final
            # but we can check column, indexes and no-nans and nans
            pd.testing.assert_frame_equal(expected_df.isna(), actual_df.isna())
    else:
        pd.testing.assert_frame_equal(expected_df, actual_df)


@pytest.mark.perf
def test_find_conflicts_detect_type_mismatch_perf():
    ch = [
        ChunkMeta(
            filepath=f"{i}.c.meta",
            columns=[f"C[{j}]" for j in range(500)],
            columns_hash="c",
            index_start_end=ChunkMeta.ColumnStartEndValues("", start=i * 5, end=i * 5 + 4, dtype="int32"),
            index_hash=str(i),
            nb_rows=4,
            dtypes=["int"],
        )
        for i in range(2000)
    ]

    i = 7  # creates type mismatch at this position
    dtypes = ["int"] * 500
    dtypes[42] = dtypes[137] = "float"
    ch[i] = ChunkMeta(
        filepath=f"{i}.c.meta",
        columns=[f"C[{j}]" for j in range(500)],
        columns_hash="c",
        index_start_end=ChunkMeta.ColumnStartEndValues("", start=i * 5, end=i * 5 + 4, dtype="int32"),
        index_hash=str(i),
        nb_rows=4,
        dtypes=dtypes,
    )

    with pytest.raises(BulkValidationError):
        find_conflicts(ch)


@pytest.mark.parametrize("type1,type2", [("int", "float"), ("int", "str"), ("float", "str"), ("int", "unknown")])
def test_find_conflicts_type_mismatch(type1, type2):
    ch = [
        ChunkMeta(
            filepath="0.c.meta",
            columns=["A"],
            columns_hash="c",
            index_start_end=ChunkMeta.ColumnStartEndValues("", start=0, end=2, dtype="int32"),
            index_hash="1",
            nb_rows=4,
            dtypes=[type1],
        ),
        ChunkMeta(
            filepath="1.c.meta",
            columns=["A"],
            columns_hash="c",
            index_start_end=ChunkMeta.ColumnStartEndValues("", start=3, end=4, dtype="int32"),
            index_hash="2",
            nb_rows=4,
            dtypes=[type2],
        ),
    ]

    with pytest.raises(BulkValidationError):
        find_conflicts(ch)


def test_find_conflicts_valid_type_mismatch():
    ch = [
        ChunkMeta(
            filepath="0.c.meta",
            columns=["A", "B", "C"],
            columns_hash="c",
            index_start_end=ChunkMeta.ColumnStartEndValues("", start=0, end=2, dtype="int32"),
            index_hash="1",
            nb_rows=4,
            dtypes=["int", "float", "str"],
        ),
        ChunkMeta(
            filepath="1.c.meta",
            columns=["A", "B", "C"],
            columns_hash="c",
            index_start_end=ChunkMeta.ColumnStartEndValues("", start=3, end=4, dtype="int32"),
            index_hash="2",
            nb_rows=4,
            dtypes=["int64", "float64", "str"],
        ),
        ChunkMeta(
            filepath="2.c.meta",
            columns=["A", "B", "C"],
            columns_hash="c",
            index_start_end=ChunkMeta.ColumnStartEndValues("", start=5, end=8, dtype="int32"),
            index_hash="3",
            nb_rows=4,
            dtypes=["int32", "float32", "str"],
        ),
    ]

    conflicts = find_conflicts(ch)
    assert not conflicts


@pytest.mark.parametrize(
    "chunks,conflicting_groups",
    (
        #  all chunks are in conflict, because columns are misaligned
        [
            [
                (["A", "B"], 0, 2),
                (["A", "B"], 3, 4),
                (["A", "B", "C"], 5, 8),
            ],
            [[0, 1, 2]],
        ],
        #  all chunks are in conflict due to transient conflict, `AB` conflicts with `BC`, `BC` with `CD`
        [
            [
                (["A", "B"], 0, 2),
                (["B", "C"], 3, 4),
                (["C", "D"], 5, 8),
            ],
            [[0, 1, 2]],
        ],
        #  `ab` chunks conflicts due to index overlap, `bc` with `c` because of column alignment, no conflict on `xz`
        [
            [
                (["a", "b"], 0, 2),
                (["a", "b"], 1, 4),
                (["x", "z"], 5, 8),
                (["d", "c"], 3, 4),
                (["c"], 5, 8),
            ],
            [[0, 1], [3, 4]],
        ],
    ),
)
def test_find_conflict(chunks, conflicting_groups):
    metas = []
    for i, ch in enumerate(chunks):
        columns, start, end = ch
        metas.append(
            ChunkMeta(
                filepath=f"{i}.c.meta",
                columns=columns,
                columns_hash="".join(sorted(columns)),
                index_start_end=ChunkMeta.ColumnStartEndValues("", start=start, end=end, dtype="int32"),
                index_hash=f"{start}.{end}",
                nb_rows=end - start,
                dtypes=["int"],
            )
        )

    conflicts = find_conflicts(metas)

    expected = {"_".join(sorted(metas[i].filename for i in gr)) for gr in conflicting_groups}
    actual = {"_".join(sorted(metas.filename for metas in gr)) for gr in conflicts}
    assert expected == actual

    assert conflicts


@pytest.mark.perf
def test_find_conflicts_perf():
    # ensure can handle many chunk to find conflict, here test 2000+ chunks

    import datetime

    ch = [
        ChunkMeta(
            filepath=f"{i}.c.meta",
            columns=[f"C{i}[{j}]" for j in range(500)],
            columns_hash="c",
            index_start_end=ChunkMeta.ColumnStartEndValues("", start=i * 5, end=i * 5 + 4, dtype="int32"),
            index_hash=str(i),
            nb_rows=4,
            dtypes=["int"],
        )
        for i in range(2000)  # i*5
    ]

    # add conflicting chunk (2000) against chunk 0 and 10
    ch.append(
        ChunkMeta(
            filepath=f"2000.c.meta",
            columns=["C0[30]", "C10[36]"],
            columns_hash="c",
            index_start_end=ChunkMeta.ColumnStartEndValues("", start=3, end=100, dtype="int32"),
            index_hash="2000",
            nb_rows=4,
            dtypes=["int"],
        )
    )

    # add conflicting chunk (2001) against chunk 2
    ch.append(
        ChunkMeta(
            filepath=f"2001.c.meta",
            columns=["C2[30]", "C2[36]"],
            columns_hash="c",
            index_start_end=ChunkMeta.ColumnStartEndValues("", start=3, end=11, dtype="int32"),
            index_hash="2001",
            nb_rows=4,
            dtypes=["int"],
        )
    )

    ts = datetime.datetime.now()
    result = find_conflicts(ch)
    print("find conflicts took ", (datetime.datetime.now() - ts).total_seconds())

    # using filename to check result, use dict with len as key since order not guarantee
    expected = {
        3: {"2000.c", "0.c", "10.c"},
        2: {"2001.c", "2.c"},
    }
    actual = {len(group): {ch.filename for ch in group} for group in result}

    assert actual == expected
