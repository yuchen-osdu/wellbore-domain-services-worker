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

from typing import Iterable, AsyncIterator, Dict
from asyncio import wait, create_task, gather, Task, FIRST_COMPLETED

import pandas as pd

from osdu.core.api.storage.blob_storage_base import BlobStorageBase

from .chunk_meta import ChunkMeta
from .dataframe import load_parquet, dump_to_parquet
from . import storage_path_builder
from .errors import BulkUploadError
from .validators import validate_df
from ..logger import get_logger
from ..model.mime_types import MimeTypes


async def chunk_download_generator(
    storage: BlobStorageBase, tenant, object_paths: Iterable[str], *, ensure_order: bool = False
) -> AsyncIterator[pd.DataFrame]:
    """
    async dataframe downloader generator. Expected to be used with `async for`. The motivation of this over a regular
    `asyncio.gather` is the capability of freeing data during the stream and operate some CPU bound operation during
    I/O operations. Rather than first accumulate all data (all I/O operations first), then operate on all of them
    (all CPU bound operations).
    It's also capable of ensuring same order than the list `object_paths`.
    Might be replaced by `Task_groups` in 3.11
    :param storage:
    :param tenant:
    :param object_paths:
    :param ensure_order: if set to `True`
    :return:
    """
    done_by_name: Dict[str, Task] = dict()
    path_list = list(object_paths)

    pending_tasks = set(create_task(storage.download(tenant, p), name=p) for p in path_list)
    try:
        next_waited_task_name = path_list.pop(0) if ensure_order else None
        while pending_tasks:
            done_tasks, pending_tasks = await wait(pending_tasks, return_when=FIRST_COMPLETED)
            done_by_name.update({task.get_name(): task for task in done_tasks})

            while done_by_name:
                if next_waited_task_name:
                    if next_waited_task_name not in done_by_name:
                        assert pending_tasks  # should be in pending task, some pending tasks cannot be empty
                        break
                    task = done_by_name.pop(next_waited_task_name)
                    next_waited_task_name = path_list.pop(0) if path_list else None
                else:
                    _, task = done_by_name.popitem()

                any_exception = task.exception()
                if any_exception is not None:
                    raise any_exception

                yield load_parquet(task.result())

    except Exception:
        # cancel all remaining
        for task in pending_tasks:
            task.cancel()
        raise


async def upload_chunk(
    storage: BlobStorageBase,
    tenant,
    df: pd.DataFrame,
    df_in_parquet: bytes | None,
    record_id: str,
    session_id: str,
    *,
    reference_curve: str | None = None,
) -> ChunkMeta:
    """
    validate then upload a chunk with its chunk meta and index dataframe.
    :param storage:
    :param tenant:
    :param df: chunk dataframe
    :param df_in_parquet: dataframe in parquet if available, otherwise will be serialized in this method
    :param record_id:
    :param session_id:
    :param reference_curve:
    :return:
    """
    # 2- validate df
    validate_df(df, reference_curve)

    session_path = storage_path_builder.session_path_level_1(record_id, session_id, base_directory=None)
    chunk_meta = ChunkMeta.from_dataframe(df, base_folder=session_path, reference_curve=reference_curve)

    chunk_filepath = storage_path_builder.join(session_path, chunk_meta.filename)

    content_to_upload = df_in_parquet or dump_to_parquet(df)

    # 3- both upload meta and data
    try:
        await gather(
            storage.upload(tenant, MimeTypes.META.add_extension(chunk_filepath), chunk_meta.dump()),
            storage.upload(tenant, MimeTypes.PARQUET.add_extension(chunk_filepath), content_to_upload),
            upload_index_from_chunk(storage, tenant, chunk_meta, df),
        )

    except Exception as e:
        get_logger().exception(f"Exception occurred while uploading to blob storage for record '{record_id}'")
        raise BulkUploadError("Failed to store bulk and its metadata") from e
    return chunk_meta


async def upload_index_from_chunk(
    storage: BlobStorageBase, tenant, chunk_meta: ChunkMeta, chunk_df: pd.DataFrame, *, overwrite: bool = False
) -> pd.DataFrame:
    """
    check if index dataframe already exists,
    if not upload index dataframe. Existence is checked using built object/file name from current chunk meta.
    Index dataframe is built from the given dataframe.
    If the reference_curve is provided, reference column with its values are also part of the dataframe uploaded.
    In that case, the reference curve must belongs to the dataframe.
    The object name upload is different if reference curve is provided or not.

    :param storage:
    :param tenant:
    :param chunk_meta:
    :param chunk_df:
    :param overwrite:
    :return: index dataframe
    """

    full_object_name = chunk_meta.get_filepath(ChunkMeta.FileType.INDEX)
    index_df = pd.DataFrame(index=chunk_df.index)

    # TODO if call to `list_object` really save time/resources
    if overwrite or len(await storage.list_objects(tenant, prefix=full_object_name, max_result=1)) == 0:
        content = dump_to_parquet(index_df)
        await storage.upload(tenant, full_object_name, content)

    return index_df
