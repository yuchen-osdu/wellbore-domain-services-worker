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

""" read bulk exceptions """


class ReadBulkCaseNotSupportedException(Exception):
    pass


class BulkCurvesNotFound(Exception):
    pass


class LimitExceededError(Exception):
    def __init__(self, requested: int, limit: int, message: str | None):
        self._requested = requested
        self._limit = limit
        ex_message = message or f"Resource requested exceeds the limit. requested: {requested}, limit: {limit}."
        super().__init__(ex_message)

    @property
    def requested(self):
        return self._requested

    @property
    def limit(self):
        return self._limit


class TooManyValuesRequested(LimitExceededError):
    def __init__(self, requested: int, limit: int):
        ex_message = f"Too many values requested: {requested}. The maximum allowed is {limit}."
        super().__init__(requested, limit, ex_message)


class TooManyColumnsRequested(LimitExceededError):
    def __init__(self, requested: int, limit: int):
        ex_message = f"Too many columns requested: {requested}. The maximum allowed is {limit}."
        super().__init__(requested, limit, ex_message)


class ReadBulkInvalidParameter(Exception):
    pass


class FilteringError(Exception):
    def __init__(self, reason):
        ex_message = f"Filtering error: {reason}"
        super().__init__(ex_message)


class ReadBulkNotProcessable(Exception):
    pass


class ReadBulkNoBulkFound(Exception):
    pass
