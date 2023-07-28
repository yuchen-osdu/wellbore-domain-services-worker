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

from typing import Callable, Iterable, Optional
from dataclasses import dataclass
import re

import pandas as pd

from . import errors as exc
from .constants import WRITE_MAX_COLUMNS_COUNT, WRITE_MAX_TOTAL_VALUES_COUNT


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: Optional[str] = None


ValidationSuccess = ValidationResult(True)

DataFrameValidationFunc = Callable[[pd.DataFrame], ValidationResult]


def no_validation(_) -> ValidationResult:
    """
    Always validate the given dataframe without error/warning
    return True, ''
    """
    return ValidationSuccess


def auto_cast_columns_to_string(df: pd.DataFrame) -> ValidationResult:
    """
    If given dataframe contains columns name which is not a string, cast it
    return always returns validation success
    """
    df.columns = df.columns.astype(str)
    return ValidationSuccess


def columns_type_must_be_string(df: pd.DataFrame) -> ValidationResult:
    """Ensure given dataframe contains columns name as string only as described by WellLog schemas"""
    if all((type(t) is str for t in df.columns)):
        return ValidationSuccess
    return ValidationResult(False, "All columns type should be string")


def validate_index(df: pd.DataFrame) -> ValidationResult:
    """Ensure index"""
    if len(df.index) == 0:
        return ValidationResult(False, "Empty data")
    if not df.index.is_numeric() and not isinstance(df.index, pd.DatetimeIndex):
        return ValidationResult(False, "Index should be numeric or datetime")
    if not df.index.is_unique:
        return ValidationResult(False, "Duplicated index found")
    return ValidationSuccess


PandasReservedIndexColRegexp = re.compile(r"__index_level_\d+__")


def is_reserved_column_name(name: str) -> bool:
    """Return True if the name is a reserved column name by Pandas/Dask with PyArrow"""
    return (
        PandasReservedIndexColRegexp.match(name) is not None or name == "__null_dask_index__" or name == "_wdms_index_"
    )


def any_reserved_column_name(names: Iterable[str]) -> bool:
    """
    There are reserved name for columns which are internally used by Pandas/Dask with PyArrow to save the index.
    Save a df containing reserved name as regular columns lead to inability to read parquet file then.

    At this stage, columns used as index are already marked as index and it's not considered as columns by Pandas.
    return: True is any column uses a reserved name
    """
    return any(is_reserved_column_name(name) for name in names if type(name) is str)


def columns_not_in_reserved_names(df: pd.DataFrame) -> ValidationResult:
    if any_reserved_column_name(df.columns.tolist()):
        return ValidationResult(False, "Invalid column name")

    return ValidationSuccess


def validate_reference(df: pd.DataFrame, reference_curve: str | None) -> ValidationResult:
    if reference_curve not in df:
        return ValidationSuccess

    reference = df[reference_curve]
    if reference.hasnans:
        return ValidationResult(False, f"The reference curve '{reference_curve}' should not contains missing values.")

    if not reference.is_unique:
        return ValidationResult(
            False, f"The reference curve '{reference_curve}' should not contains duplicated values."
        )

    if not reference.is_monotonic_increasing and not reference.is_monotonic_decreasing:
        return ValidationResult(False, f"The reference curve '{reference_curve}' should be monotonic.")

    return ValidationSuccess


def validate_df(df: pd.DataFrame, reference_curve: str | None):
    """
    validate dataframe:
        - number of values
        - number of columns
        - columns must not contain reserved names
        - index must be unique, numerical or date time types
        - if reference curve in `df`, must not contained NaN, be unique and monotonic
    raise in case of invalid
    :param df:
    :param reference_curve:
    :return: None
    :raise: TooManyColumnsError, TooManyValuesError, BulkValidationError
    """
    row_count, column_count = df.shape
    if column_count > WRITE_MAX_COLUMNS_COUNT:
        raise exc.TooManyColumnsError(column_count, WRITE_MAX_COLUMNS_COUNT)
    if row_count * column_count > WRITE_MAX_TOTAL_VALUES_COUNT:
        raise exc.TooManyValuesError(row_count * column_count, WRITE_MAX_TOTAL_VALUES_COUNT)

    errors = [
        v.errors
        for v in (columns_not_in_reserved_names(df), validate_index(df), validate_reference(df, reference_curve))
        if not v.ok and v.errors
    ]

    if errors:
        raise exc.BulkValidationError(", ".join(errors))
