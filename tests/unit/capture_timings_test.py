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

import pytest
from unittest.mock import Mock, ANY, patch
from time import sleep
from wdmsworker.capture_timings import capture_timings, timeit


class AnyFloat:
    def __init__(self, unary_fn=None):
        self.unary_pred = unary_fn

    def __eq__(self, other):
        if not isinstance(other, float):
            return False
        return True if self.unary_pred is None else self.unary_pred(other)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return "AnyInt"


@pytest.mark.anyio
async def test_capture_timings_decorator():
    mock_sync = Mock()
    mock_async = Mock()

    @capture_timings("tag_sync", [mock_sync])
    def sync_fn():
        sleep(0.2)

    @capture_timings("tag_async", [mock_async])
    async def async_fn():
        sleep(0.2)

    # when called
    sync_fn()
    await async_fn()

    # then
    mock_sync.assert_called_once()
    mock_sync.assert_called_once_with(tag="tag_sync", wall=AnyFloat(lambda t: t > 0.1), cpu=AnyFloat())
    mock_async.assert_called_once()
    mock_async.assert_called_once_with(tag="tag_async", wall=AnyFloat(lambda t: t > 0.1), cpu=AnyFloat())


def test_timeit():
    with patch("wdmsworker.capture_timings.log_timings") as mock:
        with timeit("contextual time it"):
            sleep(0.2)

        # then
        mock.assert_called_once()
        mock.assert_called_once_with("contextual time it", AnyFloat(lambda t: t > 0.1), AnyFloat(), ANY)
