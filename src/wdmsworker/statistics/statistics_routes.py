# Copyright 2021 Schlumberger
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

from typing import List
from fastapi import Query

from fastapi import APIRouter, Depends, HTTPException, status

from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse

from wdmsworker.dependencies import blob_storage_dependency, tenant_dependency
from wdmsworker.statistics.bulk_statistics import BulkStatistics
from wdmsworker.statistics.models import BulkDataStatisticsResponse
from wdmsworker.statistics import exceptions as statistics_exceptions

router = APIRouter()

responses_404_examples = {
    "description": "Not found",
    "content": {
        "application/json": {
            "examples": {
                "default": {"summary": "Record not found", "value": {"detail": "Record not found"}},
                "data-not-found": {
                    "summary": "Statistics data not found",
                    "value": {
                        "errorType": "DATA_NOT_FOUND",
                        "message": "Statistics do not exist",
                    },
                },
                "stats-curves-error": {
                    "summary": "Requested curves unknown",
                    "value": {
                        "errorType": "CURVES_NOT_FOUND",
                        "message": "Requested curves unknown",
                    },
                },
                "stats-computation-error": {
                    "summary": "Computation still running",
                    "value": {
                        "errorType": "COMPUTATION_NOT_COMPLETE",
                        "message": "Statistics computation not finished yet",
                    },
                },
            }
        }
    },
}

api_description_text = """
If wanted curves is an array:
* requests "ARRAY" retrieves all dimensions of the array
* requests "ARRAY[M:N]", retrieves all dimensions between M and N.
"""

api_unit_conversion_text = (
    "No unit conversion is supported. Statistics will be returned using the same units"
    " as recorded in Curves[].CurveUnit"
)

api_supported_types_txt = """
Data types supported:
* int
* float
* date
"""


class BulkStatisticsHTTPException(Exception):
    status_code: int
    error_type: str
    message: str

    def __init__(self, status_code: int, error_type: str, message: str):
        self.status_code = status_code
        self.error_type = error_type
        self.message = message

    def to_dict(self):
        return {"errorType": self.error_type, "message": self.message}


async def http_stats_error_handler(request, e: BulkStatisticsHTTPException) -> JSONResponse:
    """
    Catches and handles pydantic validation errors
    """
    return JSONResponse(content=jsonable_encoder(e.to_dict()), status_code=e.status_code)


@router.post(
    "/data/{record_id}/{bulk_id}/statistics",
    summary="Trigger computations of record's data statistics of record's data",
    description=f"""Trigger the computation of statistics on bulk data for the record identified by the record_id
     at its bulk id.

    {api_unit_conversion_text}
    """,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Statistics or record not found"},
        status.HTTP_409_CONFLICT: {"description": "Statistics computation already running or complete"},
        status.HTTP_200_OK: {"description": "Statistics computation started"},
    },
)
async def compute_bulk_statistics(
    record_id: str,
    bulk_id: str,
    record_version: int = Query(),
    storage=Depends(blob_storage_dependency),
    tenant=Depends(tenant_dependency),
):
    try:
        return await BulkStatistics(storage, tenant).compute_bulk_statistics(record_id, bulk_id, record_version)
    except statistics_exceptions.ComputationRunningError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.get(
    "/data/{record_id}/{bulk_id}/statistics",
    summary="Returns statistics of record's data for selected curves at requested version",
    response_model=BulkDataStatisticsResponse,
    description=f"""Returns the statistics on bulk data identified by the record and given version.
    {api_description_text}

    {api_supported_types_txt}

    {api_unit_conversion_text}
    """,
    responses={404: responses_404_examples},
)
async def get_bulk_statistics_version(
    record_id: str,
    bulk_id: str,
    curves_selection: List[str] | None = Query(default=None),
    storage=Depends(blob_storage_dependency),
    tenant=Depends(tenant_dependency),
):
    try:
        stats_df, stats_meta = await BulkStatistics(storage, tenant).get_bulk_statistics(
            record_id, bulk_id, curves_selection
        )
    except statistics_exceptions.BulkCatalogNotFoundError as e:
        raise BulkStatisticsHTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            error_type=e.public_error_type,
            message="Unable to compute statistics without bulk catalog",
        )
    except (
        statistics_exceptions.StatisticsNotFoundError,
        statistics_exceptions.RequestedCurvesError,
        statistics_exceptions.ComputationNotCompleteError,
    ) as e:
        raise BulkStatisticsHTTPException(
            status_code=status.HTTP_404_NOT_FOUND, error_type=e.public_error_type, message=str(e)
        )

    # replace np.nan by string "NaN" to have unified str type values for std column
    if not stats_df.empty:
        stats_df["std"].fillna(value=str("NaN"), inplace=True)

    # only orient: 'index' or 'columns' can be read with pd.DataFrame.from_dict().
    return BulkDataStatisticsResponse(**stats_meta.dict(by_alias=True), data=stats_df.to_dict(orient="index"))
