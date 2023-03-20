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

from wdmsworker.bulk.storage_path_builder import _generate_chunk_filename_v2
from ..generate_data import generate_df, generate_df_dtype
import numpy as np
import pandas as pd


def test_generate_chunk_filename_v2_is_idempotent_any_run_machine_version():
    df = pd.DataFrame(
        {
            "c1": pd.Series([1.1, 2.2, 3.3], dtype=np.dtype("float64")),
            "c2": pd.Series([4.4, 5.5, 6.6], dtype=np.dtype("float64")),
        },
        index=range(6),
    )

    assert _generate_chunk_filename_v2(df) == "KNLSPO6OPGSWMCXX.E3VADFB5CTYGNDQO", str(df.dtypes)


def test_generate_chunk_filename_v2_parts_variance():
    ref_df = generate_df_dtype({"A": "int", "B": "float"}, index=range(6))
    idx_hash, col_hash = _generate_chunk_filename_v2(ref_df).split(".")

    actual_idx_hash, actual_col_hash = _generate_chunk_filename_v2(
        generate_df_dtype({"A": "float", "D": "float"}, index=range(6))
    ).split(".")
    assert actual_idx_hash == idx_hash
    assert actual_col_hash != col_hash

    # on column name
    actual_idx_hash, actual_col_hash = _generate_chunk_filename_v2(
        generate_df_dtype({"A": "int", "D": "float"}, index=range(6))
    ).split(".")
    assert actual_idx_hash == idx_hash
    assert actual_col_hash != col_hash

    # on -/+ column
    actual_idx_hash, actual_col_hash = _generate_chunk_filename_v2(
        generate_df_dtype({"A": "int"}, index=range(6))
    ).split(".")
    assert actual_idx_hash == idx_hash
    assert actual_col_hash != col_hash
    actual_idx_hash, actual_col_hash = _generate_chunk_filename_v2(
        generate_df_dtype({"A": "int", "B": "float", "C": "float"}, index=range(6))
    ).split(".")
    assert actual_idx_hash == idx_hash
    assert actual_col_hash != col_hash

    # on index
    actual_idx_hash, actual_col_hash = _generate_chunk_filename_v2(
        generate_df_dtype({"A": "int", "B": "float"}, index=range(1, 7))
    ).split(".")
    assert actual_idx_hash != idx_hash
    assert actual_col_hash == col_hash
