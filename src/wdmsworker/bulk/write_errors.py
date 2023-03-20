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

""" write bulk exceptions """


class BulkUnprocessable(Exception):
    def __init__(self, reason: str | None = None):
        reason = reason or "unable to process provided data, either malformed or unsupported format"
        ex_message = f"Unprocessable data: {reason}"
        super().__init__(ex_message)


class BulkValidationError(Exception):
    pass


class BulkUploadFailure(Exception):
    pass
