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
import asyncio
from itertools import chain, repeat
from typing import Tuple

import pandas as pd
from osdu.core.api.storage.blob_storage_base import BlobStorageBase
from osdu.core.api.storage.tenant import Tenant

from wdmsworker.bulk import storage_path_builder
from wdmsworker.bulk.catalog import BulkCatalog
from wdmsworker.bulk.reader import (
    _load_same_shape_dataframes_from_storage,
    _read_index,
)
from wdmsworker.capture_timings import timeit

# todo: handle reading bulk data without catalog


async def read_bulk_for_stats(
    storage: BlobStorageBase, tenant: Tenant, bulk_catalog: BulkCatalog, columns_to_load: Tuple[str]
):
    """Code copied from wdmsworker/reader module to read bulk data when a catalog is provided"""
    base_chunk_path = storage_path_builder.record_path_level_0(bulk_catalog.record_id, base_directory=None)

    chunk_groups = bulk_catalog.filter_group_for_columns(columns_to_load)

    # not putting offset, limit here because each chunk may not cover the full bulk index
    # by the way it might be possible to do something before concat
    index_df_task = asyncio.create_task(_read_index(storage, tenant, bulk_catalog))

    load_chunk_df_coros = [
        _load_same_shape_dataframes_from_storage(
            storage,
            tenant,
            [storage_path_builder.join(base_chunk_path, p) for p in chunk_group.paths],
            [col for col in columns_to_load if col in chunk_group.labels],
        )
        for chunk_group in chunk_groups
    ]

    with timeit(f"load {len(chunk_groups)} chunk dataframes and index dataframes"):
        dfs = await asyncio.gather(*load_chunk_df_coros)  # chunks

    index_df = await index_df_task

    # concat df + select rows if needed
    with timeit(f"concat {len(dfs)} dataframes"):
        # TODO check concat when dfs are smaller than index
        final_df = pd.concat(chain(repeat(index_df, 1), dfs), axis=1, copy=False)

    return final_df
