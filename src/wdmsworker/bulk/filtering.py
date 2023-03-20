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

import ast
import operator
from functools import reduce
from typing import List
import re

from ..model.filtering_model import BulkValueFilterOperator, BulkValueFilter, ValueFilters
from .read_errors import FilteringError


def apply_bulk_filters(dataframe, filters: ValueFilters):
    """
    apply the given bulk filter on the dataframe
    :param dataframe: dataframe on which apply the filters
    :param filters: the filters
    return filtered dataframe
    """

    if filters is None:
        return dataframe

    def _create_filter_func(col_name, _operator, value):
        try:
            new_value = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            new_value = value
        if dataframe[col_name].dtype == object:
            if isinstance(new_value, tuple):
                new_value = [str(v) for v in new_value]
            else:
                new_value = str(new_value)

        if _operator == BulkValueFilterOperator.In:
            # special case when filtering cannot be done with Python operator
            return dataframe[col_name].isin(new_value)

        _op = ValueFilters.operator_to_function[_operator]
        return _op(dataframe[col_name], new_value)

    stacked_funcs = (
        _create_filter_func(col_name, _operator, value) for col_name, _operator, value in filters.all_filters()
    )
    try:
        return dataframe.loc[reduce(operator.and_, stacked_funcs, True)]
    except ValueError as e:
        raise FilteringError("Invalid filters' value") from e


re_bulk_filter = re.compile(
    r'^("(?P<enclosed_col>.+)"|(?P<col>[^:]+)):(?P<op>'
    + "|".join(BulkValueFilterOperator.values())
    + "):(?P<value>.*)$"
)


def extract_bulk_filters(bulk_filter_query) -> List[BulkValueFilter]:
    """
    returns an iterator over all filters, each iterator provide tuple [column name, operator, value]
    """
    if not bulk_filter_query:
        return []

    result = []
    for f in bulk_filter_query:
        matches = re_bulk_filter.match(f)
        if not matches:
            raise FilteringError("Invalid filter expression")
        column = matches["col"] or matches["enclosed_col"]
        result.append(BulkValueFilter(column, BulkValueFilterOperator.from_string(matches["op"]), matches["value"]))
    return result
