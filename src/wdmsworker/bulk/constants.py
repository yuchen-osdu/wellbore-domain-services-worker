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

READ_MAX_COLUMNS_COUNT = 3_000  # restrict to max 3 000 columns
READ_MAX_TOTAL_VALUES_COUNT_FILTERED = 10_000_000  # restrict to max 10M values at once (~100MB in parquet)
READ_MAX_TOTAL_VALUES_COUNT_UNFILTERED = 100_000_000  # restrict to max 100M values at once (~1GB in parquet)


WRITE_MAX_TOTAL_VALUES_COUNT = READ_MAX_TOTAL_VALUES_COUNT_FILTERED  # restrict chunk to ~100MB
WRITE_MAX_COLUMNS_COUNT = READ_MAX_COLUMNS_COUNT
WRITE_MAX_CONFLICTED_COLUMNS_COUNT = 10_000  # restrict number of conflicted columns per session
