# Copyright 2023 SLB
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
from typing import List, Literal, Iterable
from pydantic import BaseModel, Field
from fastapi.responses import Response
from fastapi import status

from .mime_types import MimeTypes
from ..bulk.constants import READ_MAX_TOTAL_VALUES_COUNT_FILTERED, READ_MAX_COLUMNS_COUNT
from ..bulk.errors import LimitExceededError


def to_json_response(model: BaseModel, status_code: int = status.HTTP_200_OK) -> Response:
    """
    build a JSON response from a pydantic model excluding unset, defaults and none
    :param model: model to dump into json
    :param status_code: by default 200
    :return:
    """
    return Response(
        status_code=status_code,
        content=model.json(exclude_none=True),
        media_type=MimeTypes.JSON.type,
    )


class ReadPartition(BaseModel):
    """Read parameters matching bulk partitions"""

    # offset: int | None
    # limit: int | None
    curves: List[str] | None


class ReadLimits(BaseModel):
    values: int = READ_MAX_TOTAL_VALUES_COUNT_FILTERED
    columns: int = READ_MAX_COLUMNS_COUNT


class TooLargeReadErrorBulkDescription(BaseModel):
    totalNumberOfRows: int | None = Field(None, description="total number of row of the record bulk data")
    totalNumberOfColumns: int | None = Field(None, description="total number of column of the record bulk data")
    partitions: List[ReadPartition] | None = Field(
        None,
        description="List of read parameters matching partitions. Meant be used as it for efficient read.",
    )


class TooLargeReadErrorResponse(BaseModel):
    """Error with type response in case on read requesting that involves too much data to fetch"""

    errorType: Literal["READ_REQUEST_TOO_LARGE"] = "READ_REQUEST_TOO_LARGE"
    message: str = Field(..., description="error message")
    limits: ReadLimits = Field(ReadLimits(), description="limits for reading data per request")
    bulkDescription: TooLargeReadErrorBulkDescription | None = None

    def set_bulk_description(self, nb_rows: int, nb_columns: int, curves_partitions: Iterable[List[str]]):
        partitions = [ReadPartition(curves=c) for c in curves_partitions]
        self.bulkDescription = TooLargeReadErrorBulkDescription(
            totalNumberOfRows=nb_rows, totalNumberOfColumns=nb_columns, partitions=partitions
        )


class LimitExceededErrorResponse(BaseModel):
    """Generic error with type response when a limit is exceeded"""

    errorType: str = "LIMIT_EXCEEDED"
    message: str = Field(..., description="error message")
    actual: int = Field(..., description="actual value that exceeds the limit")
    limit: int = Field(..., description="limit allowed")

    @classmethod
    def from_exception(
        cls, ex: LimitExceededError, additional_description: str | None = None, exclude_exception_message: bool = False
    ):
        """
        Construct an instance from `LimitExceededError` exception
        :param ex: exception to built from
        :param additional_description: additional description
        :param exclude_exception_message: if `True`, message from the exception is not dumped into the response
        :return: instance of `LimitExceededErrorResponse`
        """
        message = "" if exclude_exception_message else str(ex)
        if additional_description:
            message = f"{additional_description}. {message}" if message else additional_description
        return cls.construct(message=message, actual=ex.actual, limit=ex.limit)


class ErrorWithTypeResponse(BaseModel):
    """Base error model with an error type"""

    errorType: str
    message: str
