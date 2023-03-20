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

from typing import Generator, List, NamedTuple


class MimeType(NamedTuple):
    """expected always lower case"""

    type: str
    extension: str
    alternative_types: List[str] = []

    def match(self, str_value: str) -> bool:
        if not str_value:
            return False
        normalized_value = str_value.lower()
        return any(
            (normalized_value == a_type for a_type in [self.type] + self.alternative_types)
        ) or normalized_value.replace(".", "") == self.extension.replace(".", "")


class MimeTypes:
    """
    define mime types used in the application
    Note: May be use https://docs.python.org/3/library/mimetypes.html
        mimetypes.add_type('application/x-parquet', '.parquet')
    """

    PARQUET = MimeType(
        type="application/x-parquet",
        extension=".parquet",
        alternative_types=["application/parquet"],
    )  # because https://tools.ietf.org/html/rfc6838#section-3.4

    JSON = MimeType(type="application/json", extension=".json")

    ANY = MimeType(type="*/*", extension="")

    @classmethod
    def types(cls) -> Generator[MimeType, None, None]:
        """enumerate all type"""
        for _, t in cls.__dict__.items():
            if isinstance(t, MimeType):
                yield t

    @classmethod
    def from_str(cls, value: str) -> MimeType:
        for t in cls.types():
            if t.match(value):
                return t
        raise ValueError(f"{value} does not match any supported mime types")
