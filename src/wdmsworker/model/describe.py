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

from typing import Dict, Literal, Final
from pydantic import BaseModel, Field

WDMS_INDEX_NAME = "_wdms_index_"


class ColumnBasicDescribe(BaseModel):
    """basic information of one single column"""

    name: str = Field(description="name of the column, if index them set to '_wdms_index_'")
    start: str = Field(description="value at first row")
    end: str = Field(description="value at last row")
    type: str = Field(description="type of the underlying data")


ValuesOrder = Literal["ASC", "DESC"]
ValuesOrderAscending: Final = "ASC"
ValuesOrderDescending: Final = "DESC"


class ColumnExtendedDescribe(ColumnBasicDescribe):
    hasDuplicate: bool = Field(description="boolean if the column contains any duplicated values")
    order: ValuesOrder | None = Field(
        default=None,
        description=(
            "point out if values are either increasing (ASC) or decreasing (DESC). None if values are not monotonic"
        ),
    )
    hasNan: bool = Field(description="boolean if there are any NaNs")


class DataframeBasicDescribe(BaseModel):
    rowCount: int
    columnCount: int
    index: ColumnBasicDescribe | None = Field(description="some details about the index if there's any")
    curves: Dict[str, int] = Field(description=" dictionary curve name to number of columns ")
