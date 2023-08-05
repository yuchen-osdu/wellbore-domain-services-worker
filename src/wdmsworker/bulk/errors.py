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
from sys import exc_info
from functools import wraps
from typing import Dict, Type


class BulkError(Exception):
    """Base exception for blob storage errors."""

    def __init__(self, message: str | None = None, *, original_exception=None):
        """
        :param message: stringified message object
        :param original_exception: The original exception if any
        """
        self.inner_exception = original_exception
        if message and original_exception:
            self.message = message + ". " + str(original_exception)
        elif message or original_exception:
            self.message = message or str(original_exception)
        else:
            self.message = "unknown blob storage exception"

        super().__init__(f'Bulk error: {self.message or "unknown"}')


class BulkCaseNotSupportedError(BulkError):
    pass


class CurvesNotFoundError(BulkError):
    pass


class LimitExceededError(BulkError):
    def __init__(self, actual: int, limit: int, message: str | None):
        self._actual = actual
        self._limit = limit
        ex_message = message or f"Resource exceeds the limit. actual: {actual}, limit: {limit}."
        super().__init__(ex_message)

    @property
    def actual(self):
        return self._actual

    @property
    def limit(self):
        return self._limit


class TooManyValuesError(LimitExceededError):
    def __init__(self, actual: int, limit: int):
        ex_message = f"Too many values, actual: {actual}. The maximum allowed is {limit}."
        super().__init__(actual, limit, ex_message)


class TooManyColumnsError(LimitExceededError):
    def __init__(self, actual: int, limit: int):
        ex_message = f"Too many columns, actual: {actual}. The maximum allowed is {limit}."
        super().__init__(actual, limit, ex_message)


class InvalidParameterError(BulkError):
    pass


class FilteringError(BulkError):
    def __init__(self, reason):
        ex_message = f"Filtering error: {reason}"
        super().__init__(ex_message)


class BulkNoBulkFoundError(BulkError):
    pass


class BulkUnprocessableError(BulkError):
    def __init__(self, reason: str | None = None):
        reason = reason or "unable to process provided data, either malformed or unsupported format"
        ex_message = f"Unprocessable data: {reason}"
        super().__init__(ex_message)


class BulkValidationError(BulkError):
    pass


class BulkUploadError(BulkError):
    pass


class BulkCommitError(BulkError):
    pass


class BulkCommitNoDataError(BulkError):
    errorType = "NO_DATA_TO_COMMIT"
    description = "no data to commit"


def map_errors(exception_mapping: Dict[Type[Exception], Type[BulkError]]):
    """
    Decorator to automatically map specific exception into a bulk error
    :param exception_mapping: dictionary from Exception type to BulkError. Example:
        `{FileNotFoundError: ResourceNotFoundException}` will catch FileNotFoundError and re-forward it as
        ResourceNotFoundException

        All other exceptions are ignored
    """

    def decorator_with_bulk_error(func):
        @wraps(func)
        async def async_inner(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except RuntimeError:  # runtime ones are rethrow as-it
                raise
            except Exception as ex:
                tb = exc_info()[2]
                if exception_mapping and ex.__class__ in exception_mapping:
                    raise exception_mapping[ex.__class__](original_exception=ex).with_traceback(tb)
                raise

        return async_inner

    return decorator_with_bulk_error
