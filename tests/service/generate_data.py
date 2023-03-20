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

import numpy as np

# TODO [TAG pandas dependent]
import pandas as pd


def generate_df(columns, index):
    def gen_values(col_name, size):
        if col_name.startswith("float"):
            return np.random.random_sample(size=size)
        if col_name.startswith("str"):
            return [f"string_value_{i}" for i in range(size)]
        if col_name.startswith("bool"):
            return np.random.choice(a=[False, True], size=size)
        if col_name.startswith("date"):
            return pd.date_range(start="1/1/2022", freq="s", periods=size)
        if col_name.startswith("array_"):
            array_size = int(col_name.split("_")[1])
            return [np.array(np.random.random_sample(size=array_size)) for _i in range(size)]

        return np.random.randint(-100, 1000, size=size)

    return pd.DataFrame({c: gen_values(c, len(index)) for c in columns}, index=index)


def assert_frame_equal(left, right, check_column_order=True):
    if not check_column_order:
        l_columns = left.columns.tolist()
        assert set(l_columns) == set(right.columns)
        right = right[l_columns]  # re order columns

    pd.testing.assert_frame_equal(left, right)
