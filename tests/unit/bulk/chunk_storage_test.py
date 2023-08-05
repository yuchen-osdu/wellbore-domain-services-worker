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

from asyncio import sleep
from random import randint

import pandas as pd

import pytest
from unittest.mock import AsyncMock, Mock

from wdmsworker.bulk.chunk_storage import chunk_download_generator


@pytest.mark.anyio
async def test_chunk_download_generator():
    storage = AsyncMock()

    async def download_mock(tenant, object_name: str, *args, **kwargs):
        await sleep(float(randint(100, 999)) / 1000.0)
        return pd.DataFrame({object_name: [0]}).to_parquet()

    storage.download = download_mock

    ordered_object = [str(i) for i in range(50)]
    ordered_actual = []
    unordered_actual = []
    async for d in chunk_download_generator(storage, Mock(), ordered_object, ensure_order=True):
        ordered_actual.extend(d.columns.tolist())

    async for d in chunk_download_generator(storage, Mock(), ordered_object, ensure_order=False):
        unordered_actual.extend(d.columns.tolist())

    assert ordered_actual == ordered_object
    assert unordered_actual != ordered_object  # order is very unlikely
    assert set(unordered_actual) == set(ordered_object)


@pytest.mark.anyio
async def test_chunk_download_generator_raise_exception():
    storage = AsyncMock()

    async def download_mock(tenant, object_name: str, *args, **kwargs):
        if int(object_name) > 25:
            raise ValueError("fake exception")
        return pd.DataFrame({object_name: [0]}).to_parquet()

    storage.download = download_mock

    with pytest.raises(ValueError, match="fake exception"):
        async for _ in chunk_download_generator(storage, Mock(), [str(i) for i in range(50)], ensure_order=True):
            pass

    with pytest.raises(ValueError, match="fake exception"):
        async for _ in chunk_download_generator(storage, Mock(), [str(i) for i in range(50)], ensure_order=False):
            pass
