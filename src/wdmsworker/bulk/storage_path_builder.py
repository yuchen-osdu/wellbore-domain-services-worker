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
Utility functions that gathers method to build path for bulk storage
"""

import hashlib
from os.path import relpath as os_path_relpath
from os.path import join as os_path_join, basename as os_path_basename, split as os_path_split
import pickle
import base64
from typing import Any, Tuple

"""
bulk path organization.

for each record, there's a base folder which is based on the record id (hash of it). This base folder, linked to a
given record, is named:
 - `record_path_level_0`

from this `record_path_level_0` there are 2 sub folders, `session` and `bulk`.

Under the `session` sub folder will go all data sent or generated during a session. This mainly include the chunks
and related meta file. To differentiate two sessions, there's a sub folder with named by the session id.
This sub folder with be referred as `session_path_level_1`.

Under the `bulk` will go all data either unrelated to a session (for instance when bulk are sent without session) or
generated at session commit. Similarly to session, bulk for a given version is identified by an id and so for each
there's a sub folder using this id to separate versions. A session commit, an index and the bulk catalog are generated
and then stored under this folder.
This sub folder with be referred as `bulk_path_level_1`.

Note for performance reason, chunks stored within a session are not moved nor copied from the `session` sub-folder into
the `bulk` sub-folder. Instead the bulk catalog simply reference the chunk from `record_path_level_0`.

For a record where bulk were sent within a session broken down into 2 chunks, the folder tree will looks like that:

.
└── record_id_hash (record_path_level_0)/
    ├── session/
    │   └── session_id_1/
    │       └── data (session_path_level_1)/
    │           ├── chunk1.parquet
    │           ├── chunk1.meta
    │           ├── chunk2.parquet
    │           └── chunk2.meta
    └── bulk/
        └── bulk_id_1/
            └── data (bulk_path_level_1)/
                ├── bulk_catalog.json
                └── _wdms_index_/
                    └── index.parquet


In this case `bulk_catalog` will contains chunk path related `record_path_level_0`, similar to:

chunk1-path = session/session_id_1/data/chunk1.parquet
"""


def hash_for_filename(obj: Any, size: int = 16) -> str:
    """
    generate a hash as string from an object. the hash is generated using SHA1 encode as base 32 but only
    keeping the last 16 characters by default. it uses base32 encoding so can be used safely in filename or in URL
    without additional needs of encoding not character escaping
       - last 16:

    :param obj: obj compute the hash from
    :param size: truncate length to the size provided. Default is 16, maximum is 32, minimal is 8.
        this is useful to reduce the number of characters and avoid potential storage limitation. It remains valid as
        it will be between few items, at maximum few thousands, then the collision likelihood is infinitesimal
    :return: hash as string
    """

    obj_bytes = pickle.dumps(obj, 5)
    full_hash = base64.b32encode(hashlib.sha1(obj_bytes).digest()).decode()
    if size > 31:
        return full_hash
    return full_hash[: max(8, size)]


def join(path, *paths) -> str:
    # enforce usage of '/' as it remains compatible with all known usage so far: Windows 10+ or Linux fs, ffspec,
    # real blob storage and blob storage emulator (e.g. Azurite)
    return os_path_join(path, *paths).replace("\\", "/")


def basename(path) -> str:
    return os_path_basename(path)


def split_path(path) -> Tuple[str, str]:
    return os_path_split(path)


def record_path_level_0(record_id: str, *, base_directory: str | None = None) -> str:
    """level 0 path for any bulk related files for a given record"""
    encoded_id = hashlib.sha1(record_id.encode()).hexdigest()
    if base_directory:
        return join(base_directory, encoded_id)
    return encoded_id


def bulk_path_level_1(record_id: str | None, bulk_id: str, *, base_directory: str | None = None) -> str:
    """
    Return the base path for any files created/generated at a given bulk id.
    if record_id is None then the path is provided related to `record_path_level_0`
    """
    if record_id is None:
        return join("bulk", bulk_id, "data")
    return join(record_path_level_0(record_id, base_directory=base_directory), "bulk", bulk_id, "data")


def session_path_level_1(record_id: str | None, session_id: str, *, base_directory: str | None = None) -> str:
    """
    returns base folder for bulk files created/generated within a session.
    if record_id is None then the path is provided related to `record_path_level_0`
    """
    if record_id is None:
        return join("session", str(session_id), "data")
    return join(record_path_level_0(record_id, base_directory=base_directory), "session", str(session_id), "data")


def record_statistics_base_path(record_id: str, bulk_id: str, api_version: str, base_directory: str | None) -> str:
    """Return the path corresponding to the statistics of specified bulk."""
    bulk_base_path = record_path_level_0(record_id, base_directory=base_directory)
    return join(bulk_base_path, "bulk", bulk_id, f"statistics.v{api_version}")


def catalog_file_path(record_id: str, bulk_id: str, *, base_directory: str | None = None) -> str:
    folder_path = bulk_path_level_1(
        record_id, bulk_id, base_directory=base_directory
    )  # base directory expected to be None because base_directory already inside tenant
    return join(folder_path, "bulk_catalog.json")


def relpath(path, start) -> str:
    # enforce usage of '/' as it remains compatible with all known usage so far: Windows 10+ or Linux fs, ffspec,
    # real blob storage and blob storage emulator (e.g. Azurite)
    return os_path_relpath(path, start).replace("\\", "/")


def record_relative_path(record_id: str, path: str, *, base_directory: str | None = None) -> str:
    """Returns the path relative to the specified record."""
    base_path = record_path_level_0(record_id, base_directory=base_directory)
    return relpath(path, base_path)
