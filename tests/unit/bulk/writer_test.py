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

import uuid

import pandas as pd
import pytest
from unittest.mock import patch, AsyncMock, Mock
from osdu.core.api.storage.blob_storage_base import BlobStorageBase

from wdmsworker.bulk import storage_path_builder
from wdmsworker.bulk.catalog import async_load_bulk_catalog_with_blob_storage
from wdmsworker.bulk.write_errors import BulkValidationError, BulkUploadFailure, BulkUnprocessable
from wdmsworker.model.mime_types import MimeTypes, MimeType
from wdmsworker.bulk.dataframe import dump_df
from wdmsworker.bulk.writer import write_bulk
from wdmsworker.bulk.dataframe import load_df

from ..generate_data import generate_df, assert_frame_equal

format_params = [
    pytest.param(MimeTypes.PARQUET, id="parquet"),
    pytest.param(MimeTypes.JSON, id="json"),
]


@pytest.mark.anyio
@pytest.mark.parametrize("content_type", format_params)
@pytest.mark.parametrize("with_ref", [True, False])
async def test_write_bulk(bulk_storage_mock: BlobStorageBase, test_tenant, content_type: MimeType, with_ref: bool):
    reference_df = generate_df(["floatB", "floatA[1]", "floatA[0]"], index=range(6))
    reference_df["MD"] = list(range(3, 9))
    record_id = str(uuid.uuid4())

    bulk_id, descr = await write_bulk(
        bulk_storage_mock,
        test_tenant,
        dump_df(reference_df, content_type),
        content_type,
        record_id,
        "MD" if with_ref else None,
    )

    # check output
    assert bulk_id is not None
    assert descr.rowCount == len(reference_df)
    df_column_desc = descr.reference.start_end_df()
    expected_column_desc = reference_df.iloc[[0, -1]].copy()
    expected_column_desc["_wdms_index_"] = expected_column_desc.index
    expected_column_desc = expected_column_desc[["MD" if with_ref else "_wdms_index_"]]

    pd.testing.assert_frame_equal(expected_column_desc, df_column_desc)

    # then catalog just be there
    catalog = await async_load_bulk_catalog_with_blob_storage(bulk_storage_mock, test_tenant, record_id, bulk_id)
    assert catalog.record_id == record_id
    assert catalog.nb_rows == len(reference_df)
    assert catalog.chunk_count == 1
    assert catalog.all_columns == set(reference_df.columns)

    base_chunk_path = storage_path_builder.record_path_level_0(record_id)
    full_chunk_path = storage_path_builder.join(base_chunk_path, list(catalog.get_chunk_paths())[0])
    content = await bulk_storage_mock.download(test_tenant, full_chunk_path)
    stored_df = load_df(content, MimeTypes.PARQUET)
    assert_frame_equal(reference_df, stored_df)


@pytest.mark.anyio
@pytest.mark.parametrize("content_type", format_params)
async def test_write_bulk_validation_failure_reserved_named(
    bulk_storage_mock: BlobStorageBase, test_tenant, content_type: MimeType
):
    reference_df = generate_df(["__index_level_1__"], index=range(6))
    with pytest.raises(BulkValidationError):
        await write_bulk(bulk_storage_mock, test_tenant, dump_df(reference_df, content_type), content_type, "record_id")


@pytest.mark.anyio
async def test_write_bulk_raise_unprocessable_data():
    content_type = MimeTypes.JSON
    reference_df = generate_df(["A", "V"], index=range(6))
    with patch("wdmsworker.bulk.writer.load_df", Mock(side_effect=Exception("Test"))):
        with pytest.raises(BulkUnprocessable):
            await write_bulk(AsyncMock(), Mock(), dump_df(reference_df, content_type), content_type, "record_id")

    with pytest.raises(BulkUnprocessable):
        await write_bulk(AsyncMock(), Mock(), b"invalid parquet", MimeTypes.PARQUET, "record_id")


@pytest.mark.anyio
@pytest.mark.parametrize("content_type", format_params)
@pytest.mark.parametrize(
    "index",
    [
        pytest.param(["a", "b"], id="non_numerical"),
        pytest.param([0, 1, 1], id="non_unique"),
    ],
)
async def test_write_bulk_validation_failure_bad_index(
    bulk_storage_mock: BlobStorageBase, test_tenant, content_type: MimeType, index
):
    reference_df = generate_df(["A"], index=index)
    with pytest.raises(BulkValidationError):
        await write_bulk(bulk_storage_mock, test_tenant, dump_df(reference_df, content_type), content_type, "record_id")


@pytest.mark.anyio
async def test_write_upload_failure_raise_an_error(bulk_storage_mock: BlobStorageBase, test_tenant):
    with patch.object(bulk_storage_mock, "upload", AsyncMock(side_effect=Exception("Test"))):
        with pytest.raises(BulkUploadFailure):
            await write_bulk(
                bulk_storage_mock,
                test_tenant,
                dump_df(generate_df(["A"], index=[1, 2]), MimeTypes.JSON),
                MimeTypes.JSON,
                "record_id",
            )
