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

import pytest

from .generate_data import generate_df, assert_frame_equal
from io import BytesIO
import pandas as pd


# TODO [TAG pandas dependent]
def test_write_without_session(test_client):
    reference_df = generate_df(["floatB", "floatA[1]", "floatA[0]"], index=range(6))
    reference_df["MD"] = list(range(3, 9))
    content = reference_df.to_parquet(index=True)

    # WHEN write
    response = test_client.post(
        "/data/my_record_id?reference=MD", data=content, headers={"Content-Type": "application/parquet"}
    )

    # THEN
    assert response.status_code == 200
    response_obj = response.json()
    bulk_id = response_obj["bulkid"]
    assert bulk_id is not None
    describe_obj = response_obj["describe"]
    assert describe_obj["rowCount"] == len(reference_df)
    assert describe_obj["columnCount"] == len(reference_df.columns)
    assert describe_obj["index"]["start"] == str(reference_df.index[0])
    assert describe_obj["index"]["end"] == str(reference_df.index[-1])
    assert describe_obj["index"]["type"] == str(reference_df.index.dtype)

    assert response_obj["reference"]["name"] == "MD"
    assert response_obj["reference"]["start"] == "3"
    assert response_obj["reference"]["end"] == "8"
    assert not response_obj["reference"]["hasDuplicate"]
    assert response_obj["reference"]["order"] == "ASC"
    assert not response_obj["reference"]["hasNan"]

    # WHEN read
    response = test_client.get(f"/data/my_record_id/{bulk_id}", headers={"accept": "application/parquet"})
    assert response.status_code == 200
    actual_df = pd.read_parquet(BytesIO(response.content))
    assert_frame_equal(reference_df, actual_df, check_column_order=False)


@pytest.mark.parametrize(
    "advanced_filter, curve_list, expected_code, expected_row_nb, expected_cols",
    [
        (None, None, 200, 6, ["MD", "floatA[0]", "floatA[1]", "floatB"]),
        (None, "MD,floatB", 200, 6, ["MD", "floatB"]),
        ("MD:gt:5", None, 200, 3, ["MD", "floatA[0]", "floatA[1]", "floatB"]),
        ("MD:gt:5", "floatA[0],floatB", 200, 3, ["floatA[0]", "floatB"]),
    ],
)
def test_simple_describe(test_client, advanced_filter, curve_list, expected_code, expected_row_nb, expected_cols):
    reference_df = generate_df(["floatB", "floatA[1]", "floatA[0]"], index=range(6))
    reference_df["MD"] = list(range(3, 9))
    content = reference_df.to_parquet(index=True)

    # WHEN write
    response = test_client.post(
        "/data/my_record_id?reference=MD", data=content, headers={"Content-Type": "application/parquet"}
    )

    # THEN
    assert response.status_code == 200
    response_obj = response.json()
    bulk_id = response_obj["bulkid"]
    assert bulk_id is not None

    # WHEN read
    read_params = {"describe": True}
    if advanced_filter is not None:
        read_params["filter"] = advanced_filter
    if curve_list:
        read_params["curves"] = curve_list
    response = test_client.get(
        f"/data/my_record_id/{bulk_id}", headers={"accept": "application/parquet"}, params=read_params
    )

    # THEN
    assert response.status_code == expected_code
    if expected_code != 200:
        return

    assert response.headers["content-type"] == "application/json"
    response_json = response.json()
    assert response_json["numberOfRows"] == expected_row_nb
    assert response_json["columns"] == expected_cols


def test_write_without_session_invalid_data_should_422(test_client):
    # WHEN write invalid data
    response = test_client.post(
        "/data/my_record_id", data=b"invalid parquet", headers={"Content-Type": "application/parquet"}
    )

    # THEN should get back an 422 error
    assert response.status_code == 422
    assert response.text  # some minimal description also provided


# TODO [TAG pandas dependent]
def test_write_without_session_invalid_index(test_client):
    reference_df = generate_df(["floatB", "floatA[1]", "floatA[0]"], index=[1, 5, 4, 4])
    content = reference_df.to_parquet(index=True)

    # WHEN write
    response = test_client.post("/data/my_record_id", data=content, headers={"Content-Type": "application/parquet"})

    # THEN should get back an 400 error
    assert response.status_code == 400
    assert "index" in response.text.lower()  # some minimal description about index also provided


# TODO [TAG pandas dependent]
def test_incorrect_filters_exception(test_client):
    reference_df = generate_df(["floatB", "floatC", "floatA"], index=range(6))
    content = reference_df.to_parquet(index=True)

    # WHEN write
    response = test_client.post("/data/my_record_id", data=content, headers={"Content-Type": "application/parquet"})

    # THEN
    assert response.status_code == 200
    bulk_id = response.json()["bulkid"]

    unknown_col_params = {"filter": "UnknownColumnName:gt:100"}
    # WHEN read
    response = test_client.get(
        f"/data/my_record_id/{bulk_id}",
        headers={"accept": "application/parquet"},
        params=unknown_col_params,
    )
    assert response.status_code == 400
    response_json = response.json()["detail"]
    assert "Filtering error: Requested columns '['UnknownColumnName']' for filtering do not exist" == response_json

    unknown_operator_params = {"filter": "floatB:unknownOperator:100"}
    # WHEN read
    response = test_client.get(
        f"/data/my_record_id/{bulk_id}",
        headers={"accept": "application/parquet"},
        params=unknown_operator_params,
    )
    assert response.status_code == 422
