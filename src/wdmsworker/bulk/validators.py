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

from typing import Callable, Iterable, List, Optional
from dataclasses import dataclass
import re

# TODO [TAG pandas dependent]
import pandas as pd


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: Optional[str] = None


ValidationSuccess = ValidationResult(True)

DataFrameValidationFunc = Callable[[pd.DataFrame], ValidationResult]


# TODO [TAG pandas dependent]
def validate_all(dataframe: pd.DataFrame, validation_funcs: List[DataFrameValidationFunc]) -> ValidationResult:
    """call one or more validation function and throw BulkNotProcessable in case of invalid, run all validation before
    returning"""
    if not validation_funcs:
        return ValidationSuccess
    results = [fn(dataframe) for fn in validation_funcs]

    if not all(r.ok for r in results):
        return ValidationResult(False, ",".join([r.errors for r in results if not r.ok and r.errors]))
    return ValidationSuccess


# the following functions are stateless and without side-effect so can be easily used in parallel/cross process context


def no_validation(_) -> ValidationResult:
    """
    Always validate the given dataframe without error/warning
    return True, ''
    """
    return ValidationSuccess


# TODO [TAG pandas dependent]
def auto_cast_columns_to_string(df: pd.DataFrame) -> ValidationResult:
    """
    If given dataframe contains columns name which is not a string, cast it
    return always returns validation success
    """
    df.columns = df.columns.astype(str)
    return ValidationSuccess


# TODO [TAG pandas dependent]
def columns_type_must_be_string(df: pd.DataFrame) -> ValidationResult:
    """Ensure given dataframe contains columns name as string only as described by WellLog schemas"""
    if all((type(t) is str for t in df.columns)):
        return ValidationSuccess
    return ValidationResult(False, "All columns type should be string")


# TODO [TAG pandas dependent]
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


# TODO [TAG pandas dependent]
def columns_not_in_reserved_names(df: pd.DataFrame) -> ValidationResult:
    if any_reserved_column_name(df.columns.tolist()):
        return ValidationResult(False, "Invalid column name")

    return ValidationSuccess
