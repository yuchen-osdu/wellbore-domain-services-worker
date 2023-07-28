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

from enum import Enum
from dataclasses import dataclass
import operator
from typing import Iterable, List, Set, NamedTuple, Dict

from wdmsworker.bulk.errors import FilteringError


class BulkValueFilterOperator(str, Enum):
    Less = "lt"
    LessOrEqual = "lte"
    Greater = "gt"
    GreaterOrEqual = "gte"
    Equal = "eq"
    NotEqual = "neq"
    In = "in"

    @classmethod
    def from_string(cls, value: str) -> "BulkValueFilterOperator":
        value = value.lower()
        # ignore mypy check error due to https://github.com/python/mypy/issues/12682
        op = next(filter(lambda e: e.value == value, cls), None)  # type: ignore
        if op:
            return op
        raise FilteringError("invalid operator: " + value)

    @classmethod
    def values(cls) -> List[str]:
        return [e.value for e in cls]


class BulkValueFilter(NamedTuple):
    """Represent on filter to be applied on values of one column of dataframe"""

    column: str
    operator: BulkValueFilterOperator
    value: str


class ValueFilters:
    """Represent filters to be applied on index of loaded dataframe"""

    operator_to_function = {
        BulkValueFilterOperator.Equal: operator.eq,
        BulkValueFilterOperator.NotEqual: operator.ne,
        BulkValueFilterOperator.LessOrEqual: operator.le,
        BulkValueFilterOperator.Less: operator.lt,
        BulkValueFilterOperator.Greater: operator.gt,
        BulkValueFilterOperator.GreaterOrEqual: operator.ge,
    }

    def __init__(self, filters: Iterable[BulkValueFilter]):
        """
        Construct BulkValueFilters and validate inputs
        :param filters: iterable tuple[column, operator, value]
        :throw: FilteringError
        return BulkValueFilters object
        """
        column_operators: Dict[str, Set[BulkValueFilterOperator]] = {}
        self._filters = []
        for column_name, _operator, value in filters:
            operators = column_operators.setdefault(column_name, set())
            if _operator in operators:
                raise FilteringError("Same operator on the same column")
            operators.add(_operator)
            self._filters.append(BulkValueFilter(column_name, _operator, value))

        for _, operators in column_operators.items():
            if BulkValueFilterOperator.Equal in operators and BulkValueFilterOperator.In in operators:
                raise FilteringError(
                    f"Operator '{BulkValueFilterOperator.Equal}' and '{BulkValueFilterOperator.In}' "
                    "can't be applied on the same column"
                )

    @property
    def columns(self) -> Set[str]:
        return set((c for c, *_ in self._filters))

    def has_filter(self) -> bool:
        return bool(self._filters)

    def all_filters(self) -> List[BulkValueFilter]:
        return self._filters


class IndexFilters:
    """Represent filters to be applied on index of loaded dataframe"""

    def __init__(self, offset: int | None, limit: int | None):
        if offset and offset < 1:
            offset = None
        if limit and limit < 1:
            raise ValueError("limit parameter must be 1 or more")
        self.offset = offset
        self.limit = limit

    def row_count(self, total_rows: int) -> int:
        filtered_row_count = total_rows
        if self.offset:
            filtered_row_count = max(0, total_rows - self.offset)
        if self.limit:
            filtered_row_count = min(self.limit, filtered_row_count)

        return filtered_row_count

    def update_from_row_count(self, total_rows):
        if self.limit is not None and self.limit >= total_rows:
            self.limit = None


@dataclass(frozen=True)
class BulkFilters:
    """Class that regroup all attributes necessary to apply filters on loaded dataframe"""

    index_filters: IndexFilters
    value_filters: ValueFilters | None
    curves_are_array: bool | None  # TODO does really belongs here
    requested_columns: List[str] | None
    curves_order_requested: bool
