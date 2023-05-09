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

"""
Module containing high level functions to write bulk data
"""

import uuid
from io import BytesIO
import asyncio
from typing import Tuple, Optional

from osdu.core.api.storage.blob_storage_base import BlobStorageBase


from .validators import validate_all, columns_not_in_reserved_names, validate_index
from . import storage_path_builder
from .catalog import build_chunk_metadata_json
from .dataframe import load_df, basic_describe, column_describe
from .catalog import BulkCatalog, async_save_bulk_catalog_with_blob_storage
from ..model.describe import DataframeBasicDescribe, ColumnExtendedDescribe
from ..model.mime_types import MimeType, MimeTypes
from . import write_errors as exc
from ..logger import get_logger
from ..capture_timings import capture_timings


async def write_bulk_data_in_session(
    storage: BlobStorageBase, tenant, content: bytes, content_type: MimeType, record_id: str, session_id: str
) -> DataframeBasicDescribe:
    """
    Add a bulk chunk within a session
    :param storage:
    :param tenant:
    :param content:
    :param content_type:
    :param record_id:
    :param session_id:
    :return:
    :throws: BulkValidationError, BulkUploadFailure
    """
    # 1- deserialize the dataframe
    df = load_df(BytesIO(content), content_type)

    # 2- validate df
    # TODO validation is incomplete
    validation = validate_all(df, [columns_not_in_reserved_names, validate_index])
    if not validation.ok:
        raise exc.BulkValidationError(validation.errors)

    # store df + associated meta,
    session_path = storage_path_builder.session_path_level_1(
        record_id=record_id, session_id=session_id, base_directory=None
    )
    chunk_filename = storage_path_builder.generate_chunk_filename(df)
    chunk_filepath = storage_path_builder.join(session_path, chunk_filename)

    meta_content = build_chunk_metadata_json(df).encode()

    if content_type == MimeTypes.JSON:  # we don't need de re-serialize if already in parquet
        content = df.to_parquet(None, index=True, engine="pyarrow")

    # 3- both upload meta and data
    try:
        await asyncio.gather(
            storage.upload(tenant, chunk_filepath + ".meta", meta_content),
            storage.upload(tenant, chunk_filepath + ".parquet", content),
        )
    except Exception as e:
        get_logger().exception(f"Exception occurred while uploading to blob storage for record {record_id}: {e}")
        raise exc.BulkUploadFailure("Failed to store bulk and its metadata") from e

    return basic_describe(df)


@capture_timings("write_bulk")
async def write_bulk(
    storage: BlobStorageBase,
    tenant,
    content: bytes,
    content_type: MimeType,
    record_id: str,
    reference_curve: str | None = None,
) -> Tuple[str, DataframeBasicDescribe, Optional[ColumnExtendedDescribe]]:
    """
    Write whole bulk (no session)
    :param storage:
    :param tenant:
    :param content:
    :param content_type:
    :param record_id:
    :param reference_curve: name of the reference curve, if not `None` will return a describe of it
    :return: tuple bulkid, describe
    :throws: BulkValidationError, BulkUploadFailure, BulkUnprocessable
    """

    # 1- deserialize the dataframe
    try:
        df = load_df(content, content_type)
    except Exception as e:
        raise exc.BulkUnprocessable() from e

    if df.empty:
        raise exc.BulkUnprocessable("empty bulk")

    # TODO required for Dask to resolve conflict, should not be needed once write fully moved to worker
    # df.index.name = "_wdms_index_"

    # 2- validate df
    validation = validate_all(df, [columns_not_in_reserved_names, validate_index])
    if not validation.ok:
        raise exc.BulkValidationError(validation.errors)

    ref_describe = None
    if reference_curve:
        try:
            ref_describe = column_describe(df, reference_curve)
        except ValueError as e:
            raise exc.BulkValidationError(f'curve "{reference_curve}" not found') from e

    # 3- build blob filename
    bulk_id = str(uuid.uuid4())
    bulk_base_path = storage_path_builder.bulk_path_level_1(record_id=record_id, bulk_id=bulk_id, base_directory=None)
    full_file_path = storage_path_builder.join(
        bulk_base_path, storage_path_builder.generate_chunk_filename(df) + ".parquet"
    )

    # 4- generate catalog
    if content_type == MimeTypes.JSON:  # we don't need de re-serialize if already in parquet
        content = df.to_parquet(None, index=True, engine="pyarrow")

    catalog = BulkCatalog.from_single_dataframe(record_id, full_file_path, df)

    # 5- both upload meta and data
    try:
        await asyncio.gather(
            async_save_bulk_catalog_with_blob_storage(storage, tenant, bulk_id, catalog),
            storage.upload(tenant, full_file_path, content),
        )
    except Exception as e:
        get_logger().exception(f"Exception occurred while uploading to blob storage for record {record_id}: {e}")
        raise exc.BulkUploadFailure("Failed to store bulk and its metadata") from e

    return bulk_id, basic_describe(df), ref_describe
