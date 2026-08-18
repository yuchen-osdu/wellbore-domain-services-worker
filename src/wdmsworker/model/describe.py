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

from typing import Dict, Tuple, Any
from enum import Enum

import pandas as pd
from pydantic import BaseModel, Field

WDMS_INDEX_NAME = "_wdms_index_"


class Monotonicity(str, Enum):
    Increasing = "increasing"
    Decreasing = "decreasing"

    @classmethod
    def from_series(cls, series: pd.Series):
        if series.is_monotonic_increasing:
            return Monotonicity.Increasing
        if series.is_monotonic_decreasing:
            return Monotonicity.Decreasing
        return None


DataframeDictSplit = Dict
"""orient 'split' serialisation, see https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.to_dict.html"""


class ColumnDescribe(BaseModel):
    """
    information on a single column containing the following information:
        - name: name or label of the column. If the column refers to the index, name with set to "_wdms_index_"
        - monotonicity: if set to `None`, the values are not monotonic. Set to `increasing` if monotonic increasing,
                        to `decreasing if monotonic decreasing. By convention and backward compatibility, set to
                        `increasing` in case of empty dataframe.
        - hasDuplicate: flag if values are not unique.
        - hasNan: flag if values contains at least one missing value.
        - dataType: data type of the values as string, e.g. `int64`. Set to `None` if dataframe is empty
        - startEnd: dataframe serialized as dict/json which contains only the associated column with only its first and
                    last rows with index preserved. Pandas dataframe can be directly constructed from this dict.
                    In some cases, it could contains a single row or be empty if original dataframe contains a single
                    row or is empty.
    """

    name: str = Field(description="name of the column, if index them set to '_wdms_index_'")
    # TODO see to change start|end to the first|last not NaN value instead
    startEnd: DataframeDictSplit = Field(
        description=(
            "Simplified dataframe contains only the first and last row, with the reference column if requested."
            "See https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.to_dict.html `split` orient."
            "Dataframe can simply be constructed directly using dataframe constructor as it."
        )
    )
    monotonicity: Monotonicity | None = Field(
        None, description="If not None, data are monotonic increasing or decreasing"
    )
    hasDuplicate: bool = Field(default=False, description="boolean if the column contains any duplicated values")

    hasNan: bool = Field(default=False, description="boolean if there are any NaNs")

    dataType: str | None = Field(default=None, description="data type of the values, e.g. 'float64'")

    def start_end_df(self) -> pd.DataFrame:
        """constructs and returns a dataframe from `startEnd` dict"""
        # pandas from_dict/to_dict are unexpectedly inconsistent in orient parameters ... used "split" to serialized
        # as dict which match Dataframe constructor but not `from_dict`
        df = pd.DataFrame(**self.startEnd)
        if self.dataType and not df.empty:
            df[self.name].astype(self.dataType, copy=False)
        return df

    def start_end_values(self) -> Tuple[Any, Any]:
        return self.start_end_df()[self.name].values.tolist()

    @classmethod
    def _from_dataframe(cls, df: pd.DataFrame, name: str, *other_columns_to_include) -> "ColumnDescribe":
        if not name or name not in df:
            name = WDMS_INDEX_NAME

        if df.empty and df.index.empty:
            # in that case, still produce an instance
            reduced_df = df
            column_series = pd.Series(dtype="object")
        else:
            columns = [name]
            if name == WDMS_INDEX_NAME:
                column_series = df.index
            else:
                column_series = df[name]

            # unknown columns are dropped
            columns.extend(c for c in other_columns_to_include if c in df)

            # constructed reduced df that only contains first and last row with the columns requested. If, for some
            # reason there no columns, because it's not possible of have a dataframe with no columns (only an index)
            # the dataframe will contains a '_wdms_index_' containing the same values than the index.
            reduced_df = df.iloc[[0, -1]].copy() if len(df) > 1 else df.copy()
            reduced_df[WDMS_INDEX_NAME] = reduced_df.index
            reduced_df = reduced_df[columns]

        return cls(
            name=name,
            startEnd=reduced_df.to_dict("split"),
            monotonicity=Monotonicity.from_series(column_series),
            hasDuplicate=not column_series.is_unique,
            hasNan=column_series.hasnans,
            dataType=str(column_series.dtype),
        )

    @classmethod
    def from_index(cls, df: pd.DataFrame) -> "ColumnDescribe":
        """build for dataframe index only"""
        return cls._from_dataframe(df, WDMS_INDEX_NAME)

    @classmethod
    def from_column(cls, df: pd.DataFrame, column_name: str, reference: str | None = None) -> "ColumnDescribe":
        """
        build description for a specific column optionally including reference values for start end.
        If reference is None or not in df, the column is skipped and index will be used instead.
        If the column_name is not in the df, then only index is provided.
        """
        if reference and column_name in df:
            return cls._from_dataframe(df, column_name, reference)
        return cls._from_dataframe(df, column_name)


class DataframeBasicDescribe(BaseModel):
    rowCount: int
    curves: Dict[str, int] = Field(description=" dictionary curve name to number of columns ")
    reference: ColumnDescribe | None = Field(
        description=(
            "details about the reference upon request. If no reference applicable index will be described instead"
            " using name '_wdms_index_'"
        )
    )
