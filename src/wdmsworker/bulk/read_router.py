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

from fastapi import APIRouter, Depends, Query, HTTPException, status, Response
from typing import List

from .filtering import BulkValueFilterOperator, ValueFilters, extract_bulk_filters
from ..dependencies import (
    accept_dependency,
    json_orient_dependency,
    blob_storage_dependency,
    tenant_dependency,
)
from ..model.json_orient import JSONOrient
from ..model.mime_types import MimeType, MimeTypes
from .catalog import async_load_bulk_catalog_with_blob_storage
from ..logger import get_logger
from . import reader
from . import read_errors


logger = get_logger()

read_bulk_router = APIRouter()


@read_bulk_router.get("/data/{record_id}/{bulk_id}")
async def get_bulk_route(
    record_id: str,
    bulk_id: str,
    offset: int | None = Query(default=None, ge=0),
    limit: int | None = Query(default=None, ge=1),
    curves: str | None = Query(default=None),
    describe: bool | None = Query(default=False),  # TODO add regex='...'
    bulk_filter_query: List[str]
    | None = Query(
        default=None, alias="filter", regex='^(".+"|[^:]+):(' + "|".join(BulkValueFilterOperator.values()) + "):.*$"
    ),
    accept_type: MimeType = Depends(accept_dependency),
    orient: JSONOrient = Depends(json_orient_dependency),
    storage=Depends(blob_storage_dependency),
    tenant=Depends(tenant_dependency),
):
    try:
        catalog = await async_load_bulk_catalog_with_blob_storage(storage, tenant, record_id, bulk_id)
    except Exception as e:
        logger.exception(f"unexpected error while loading catalog for {record_id}, bulk_id {bulk_id}: {e}")
        raise HTTPException(500, f"unexpected failure while loading catalog for {record_id}, bulk_id {bulk_id}: {e}")

    curve_selection: List[str] | None = None
    if curves:
        # split and remove empty, using dict to remove duplicate but maintain order
        curves = {curve.strip(): None for curve in curves.split(",") if curve}  # type: ignore
        if curves:
            curve_selection = list(dict.fromkeys(curves))

    bulk_filters = ValueFilters(extract_bulk_filters(bulk_filter_query))

    # if describe without filters, the catalog is enough to answer:
    if catalog and describe and not bulk_filters.has_filter():
        nb_rows, columns = catalog.describe(offset=offset, limit=limit, column_selection=curve_selection)
        return _build_describe_response(nb_rows, columns)

    try:
        if catalog is None:
            read_result = await reader.read_bulk_outside_session(
                storage,
                tenant,
                record_id,
                bulk_id,
                accept_type,
                orient,
                offset,
                limit,
                curve_selection,
                bulk_filters,
                describe,
            )
        else:
            read_result = await reader.read_bulk(
                storage, tenant, catalog, accept_type, orient, offset, limit, curve_selection, bulk_filters, describe
            )
        return Response(read_result.content, media_type=read_result.mime_type.type)

    except read_errors.ReadBulkCaseNotSupportedException:
        raise HTTPException(status.HTTP_412_PRECONDITION_FAILED)
    except read_errors.BulkCurvesNotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    except (
        read_errors.TooManyColumnsRequested,
        read_errors.TooManyValuesRequested,
        read_errors.ReadBulkInvalidParameter,
        read_errors.FilteringError,
    ) as e:
        # TODO review messages returned
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


def _build_describe_response(nb_rows: int, columns: List[str]):
    return Response(content=reader.build_json_str_from_describe(nb_rows, columns), media_type=MimeTypes.JSON.type)
