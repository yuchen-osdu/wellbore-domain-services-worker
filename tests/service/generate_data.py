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

import pandas as pd


def generate_df(columns, index, reference: str | None = None) -> pd.DataFrame:
    """
    generate a dataframe with random values of the type requested. if `reference` provided, the corresponding values
    produced are monotonic increasing instead of random
    :param columns: list of column labels, if starts with `float`, `str`, `bool`, `date`, values are generated
                    in the respective type. If starts with `array` then it generates `float` values. Default is `int`
    :param index: index values
    :param reference: reference curve name, corresponding values will be increasing between index edges. Type must be
                      `float`, `int` or `date`. By default generates `int` values.
    """
    index_values = list(index)

    def gen_values(col_name, size, monotonic):
        if col_name.startswith("float"):
            if monotonic:
                return np.linspace(float(index_values[0]), float(index_values[-1]), size, endpoint=False)
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

        if monotonic:
            return index_values
        return np.random.randint(-100, 1000, size=size)

    return pd.DataFrame({c: gen_values(c, len(index_values), c == reference) for c in columns}, index=index_values)


def assert_frame_equal(left, right, check_column_order=True):
    # TODO temporary: due to Dask compatibility until write fully moved to workers, index name might be different
    #  so reset the name
    left.index.name = None
    right.index.name = None

    if not check_column_order:
        l_columns = left.columns.tolist()
        assert set(l_columns) == set(right.columns)
        right = right[l_columns]  # re order columns

    pd.testing.assert_frame_equal(left, right)


def generate_date_range(size):
    return pd.date_range(start="1/1/2022", freq="s", periods=size)


def generate_df_dtype(columns: dict, index, reference: str | None = None) -> pd.DataFrame:
    """
    generate a dataframe with random values of the type requested. if `reference` provided, the corresponding values
    produced are monotonic increasing instead of random

    :param columns: dictionary `{column_label: value_type}`
    :param index: index values
    :param reference: reference curve name, corresponding values will be increasing between index edges. Type must be
                      `float`, `int` or `date`. By default generates `int` values.
    """
    index_values = list(index)

    def gen_values(dtype, size, monotonic):
        if dtype == "float":
            if monotonic:
                return np.linspace(float(index_values[0]), float(index_values[-1]), size, endpoint=False)
            return np.random.random_sample(size=size)
        if dtype == "str":
            return [f"string_value_{i}" for i in range(size)]
        if dtype == "bool":
            return np.random.choice(a=[False, True], size=size)
        if dtype == "datetime":
            return generate_date_range(size)
        if monotonic:
            return index_values
        return np.random.randint(-100, 1000, size=size)

    return pd.DataFrame(
        {c: gen_values(d, len(index_values), c == reference) for c, d in columns.items()}, index=index_values
    )
