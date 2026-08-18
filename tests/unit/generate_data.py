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
from io import BytesIO, StringIO
import hashlib

import numpy as np

import pandas as pd

from wdmsworker.model.mime_types import MimeTypes


def generate_df(columns, index):
    def gen_values(col_name, size):
        if isinstance(col_name, str):
            if col_name.startswith("float"):
                return np.random.random_sample(size=size)
            if col_name.startswith("str"):
                return [f"string_value_{i}" for i in range(size)]
            if col_name.startswith("bool"):
                return np.random.choice(a=[False, True], size=size)
            if col_name.startswith("date"):
                return generate_date_range(size)
            if col_name.startswith("array_"):
                array_size = int(col_name.split("_")[1])
                return [np.array(np.random.random_sample(size=array_size)) for _i in range(size)]

        return np.random.randint(-100, 1000, size=size)

    return pd.DataFrame({c: gen_values(c, len(index)) for c in columns}, index=index)


def generate_df_dtype(columns: dict, index):
    def gen_values(col_name, dtype, size):
        if dtype == "float":
            return np.random.random_sample(size=size)
        if dtype == "str":
            return [f"string_value_{i}" for i in range(size)]
        if dtype == "bool":
            return np.random.choice(a=[False, True], size=size)
        if dtype == "datetime":
            return generate_date_range(size)
        return np.random.randint(-100, 1000, size=size)

    return pd.DataFrame({c: gen_values(c, d, len(index)) for c, d in columns.items()}, index=index)


def generate_date_range(size):
    return pd.date_range(start="1/1/2022", freq="s", periods=size)


def assert_frame_equal(right, left):
    # reset index name as simulating previous Dask storage may result with a difference index name
    right.index.name = None
    left.index.name = None

    pd.testing.assert_frame_equal(right, left)


def assert_dataframe_from_content(expected_df, content, accept_type, orient="split", enforce_column_order=False):
    if accept_type == MimeTypes.PARQUET:
        actual_df = pd.read_parquet(BytesIO(content))
    else:
        actual_df = pd.read_json(StringIO(content), orient=orient if isinstance(orient, str) else orient.value)
    if expected_df.empty and actual_df.empty:
        # corner case, when there's no row, just checking columns
        assert list(expected_df.columns) == list(actual_df.columns)
    else:
        # check_dtype to False as json may lose strict type
        if enforce_column_order:
            pd.testing.assert_frame_equal(expected_df, actual_df, check_dtype=accept_type == MimeTypes.PARQUET)
        else:
            assert set(expected_df.columns) == set(actual_df.columns)
            pd.testing.assert_frame_equal(
                expected_df, actual_df[expected_df.columns], check_dtype=accept_type == MimeTypes.PARQUET
            )


def generate_chunk_filename_dask_impl(dataframe: pd.DataFrame) -> str:
    import time

    first_idx, last_idx = dataframe.index[0], dataframe.index[-1]
    if isinstance(dataframe.index, pd.DatetimeIndex):
        first_idx, last_idx = dataframe.index[0].value, dataframe.index[-1].value

    shape_str = "_".join(f"{cn}:{dt}" for cn, dt in dataframe.dtypes.items())
    shape = hashlib.sha1(shape_str.encode()).hexdigest()
    cur_time = round(time.time() * 1000)
    return f"{first_idx}_{last_idx}_{cur_time}.{shape}"
