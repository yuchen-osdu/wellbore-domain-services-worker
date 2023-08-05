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


from pydantic import BaseModel
from fastapi.responses import JSONResponse, Response
from fastapi import status
from ..bulk.errors import LimitExceededError


class LimitExceededErrorResponse(BaseModel):
    message: str
    actual: int
    limit: int

    @classmethod
    def from_exception(cls, ex: LimitExceededError):
        return cls.construct(message=str(ex), actual=ex.actual, limit=ex.limit)

    def to_response(
        self, status_code: int = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, additional_description: str | None = None
    ) -> Response:
        """:return: build a response with a 413 status code by default"""
        if additional_description:
            m = LimitExceededErrorResponse.construct(
                message=f"{additional_description}. {self.message}", actual=self.actual, limit=self.limit
            )
        else:
            m = self
        return JSONResponse(m.dict(), status_code)


class ErrorWithTypeResponse(BaseModel):
    errorType: str
    message: str

    def to_response(self, status_code: int) -> Response:
        return JSONResponse(self.dict(), status_code)
