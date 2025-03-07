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
from io import BytesIO
import pandas as pd
import json

from .generate_data import generate_df, assert_frame_equal


@pytest.mark.parametrize("ref_values", [list(range(3, 9)), [2.2, 1.0, -0.55]], ids=["increasing", "decreasing"])
def test_write_without_session(test_client, ref_values):
    reference_df = generate_df(["floatB", "floatA[1]", "floatA[0]"], index=range(len(ref_values)))
    reference_df["MD"] = ref_values
    ref_series = reference_df["MD"]
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
    assert describe_obj["curves"] == {"floatB": 1, "floatA": 2, "MD": 1}
    reference_dict = describe_obj["reference"]
    assert reference_dict["name"] == "MD"
    assert reference_dict["hasNan"] == ref_series.hasnans
    assert reference_dict["hasDuplicate"] != ref_series.is_unique
    if ref_series.is_monotonic_increasing:
        assert reference_dict["monotonicity"] == "increasing"
    elif ref_series.is_monotonic_decreasing:
        assert reference_dict["monotonicity"] == "decreasing"
    else:
        assert reference_dict["monotonicity"] is None
    assert reference_dict["dataType"] == str(ref_series.dtype)
    reference_actual = pd.DataFrame(**reference_dict["startEnd"])
    values = reference_actual["MD"].values
    assert values[0] == ref_values[0]
    assert values[1] == ref_values[-1]

    # WHEN read
    response = test_client.get(f"/data/my_record_id/{bulk_id}", headers={"accept": "application/parquet"})
    assert response.status_code == 200
    actual_df = pd.read_parquet(BytesIO(response.content))
    assert_frame_equal(reference_df, actual_df, check_column_order=False)


@pytest.mark.parametrize(
    "ref_values", [[2.2, 1.0, 1.0, -0.55], [1, None, 3.3, 4.0], []], ids=["duplicate", "missing", "no content"]
)
def test_write_without_session_invalid_cases(test_client, ref_values):

    if ref_values:
        reference_df = generate_df(["floatB", "floatA[1]", "floatA[0]"], index=range(len(ref_values)))
        reference_df["MD"] = ref_values
        content = reference_df.to_parquet(index=True)
    else:
        content = None

    # WHEN write
    response = test_client.post(
        "/data/my_record_id?reference=MD", data=content, headers={"Content-Type": "application/parquet"}
    )

    # failure
    assert response.status_code == 422
    if content is None:
        assert "either malformed or unsupported format" in response.text
    else:
        assert "MD" in response.text


@pytest.mark.parametrize("ref_param", ({"reference": "MD"}, None))
def test_write_without_session_no_ref(test_client, ref_param):
    reference_df = generate_df(["floatB", "floatA[1]", "floatA[0]"], index=range(5))
    content = reference_df.to_parquet(index=True)

    # WHEN write with an unknown reference or not requested
    response = test_client.post(
        "/data/my_record_id", data=content, headers={"Content-Type": "application/parquet"}, params=ref_param
    )

    # THEN request is successful and described column used index
    assert response.status_code == 200
    response_obj = response.json()
    bulk_id = response_obj["bulkid"]
    assert bulk_id is not None
    describe_obj = response_obj["describe"]
    assert describe_obj["rowCount"] == len(reference_df)
    assert describe_obj["curves"] == {"floatB": 1, "floatA": 2}
    reference_dict = describe_obj["reference"]
    reference_df = pd.DataFrame(**reference_dict["startEnd"])
    assert "MD" not in reference_df
    assert reference_dict["name"] != "MD"
    assert not reference_dict["hasNan"]
    assert not reference_dict["hasDuplicate"]
    assert reference_dict["monotonicity"] is not None
    assert reference_dict["dataType"]
    values = reference_df[reference_df.columns[0]].values
    assert values[0] == 0
    assert values[1] == 4


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


def test_write_without_session_invalid_index(test_client):
    reference_df = generate_df(["floatB", "floatA[1]", "floatA[0]"], index=[1, 5, 4, 4])
    content = reference_df.to_parquet(index=True)

    # WHEN write
    response = test_client.post("/data/my_record_id", data=content, headers={"Content-Type": "application/parquet"})

    # THEN should get back an 422 error
    assert response.status_code == 422
    assert "index" in response.text.lower()  # some minimal description about index also provided


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
    assert "Filtering error: Requested columns '['UnknownColumnName']' for filtering do not exist" in response_json

    unknown_operator_params = {"filter": "floatB:unknownOperator:100"}
    # WHEN read
    response = test_client.get(
        f"/data/my_record_id/{bulk_id}",
        headers={"accept": "application/parquet"},
        params=unknown_operator_params,
    )
    assert response.status_code == 422


def test_basic_compute_and_get_stats(test_client):
    reference_df = generate_df(
        ["MD", "float-B", "floatC[0]", "floatC[1]", "bool-D", "date-E", "string-F"], index=range(42)
    )
    content = reference_df.to_parquet(index=True)

    record_id = "my_record_id"
    # WHEN write
    response = test_client.post(f"/data/{record_id}", data=content, headers={"Content-Type": "application/parquet"})

    # THEN
    assert response.status_code == 200
    response_obj = response.json()
    bulk_id = response_obj["bulkid"]

    get_stats_response = test_client.get(f"/data/{record_id}/{bulk_id}/statistics")
    assert get_stats_response.status_code == 404
    assert get_stats_response.json()["errorType"] == "DATA_NOT_FOUND"

    compute_stats_response = test_client.post(
        f"/data/{record_id}/{bulk_id}/statistics", params={"record_version": 123456}
    )
    assert compute_stats_response.status_code == 200, compute_stats_response.text

    get_stats_response = test_client.get(f"/data/{record_id}/{bulk_id}/statistics")
    assert get_stats_response.status_code == 200
    stats_result = get_stats_response.json()
    assert stats_result["recordId"] == record_id
    assert stats_result["computationStatus"] == "complete"

    assert sorted(stats_result["data"].keys()) == ["MD", "date-E", "float-B", "floatC[0]", "floatC[1]"]
    for col, stats_col in stats_result["data"].items():
        assert len(stats_col) == 9

    params = {"curves_selection": ["MD", "floatC"]}
    get_stats_2_cols_response = test_client.get(f"/data/{record_id}/{bulk_id}/statistics", params=params)
    assert get_stats_2_cols_response.status_code == 200
    stats_result_2_cols = get_stats_2_cols_response.json()
    assert sorted(stats_result_2_cols["data"].keys()) == ["MD", "floatC[0]", "floatC[1]"]


def test_read_json_with_float_having_zero_decimal(test_client):
    record_id = "my_record_id"
    session_id = "my-session-123456"

    # Chunk with float data with decimal .00
    json_data_1 = json.dumps(
        {
            "columns": ["int-A", "float-B", "bool-D", "date", "modified", "string-G"],
            "index": [0],
            "data": [[621, 10.00, True, "1640995200000", "2022-01-01T08:08:08 +02:00", "string_value_0"]],
        }
    )

    # Regular chunk
    json_data_2 = json.dumps(
        {
            "columns": ["int-A", "float-B", "bool-D", "date", "modified", "string-G"],
            "index": [1],
            "data": [[126, 42.9895, False, "1640995204242", "2022-02-02T08:18:18 +02:00", "string_value_1"]],
        }
    )

    # Sent chunks to service
    for _chunk in [json_data_1, json_data_2]:
        _add_session_data_response = test_client.post(
            f"/data/{record_id}/session/{session_id}", data=_chunk, headers={"Content-Type": "application/json"}
        )
        assert _add_session_data_response.status_code == 200

    # Complete session
    complete_session_response = test_client.patch(
        f"/data/{record_id}/session/{session_id}", params={"completion": "update"}
    )
    assert complete_session_response.status_code == 200, complete_session_response.text
    response_data = complete_session_response.json()
    bulk_id = response_data["bulkid"]

    # Retrieve last version of the record with chunks above
    get_record_data_response = test_client.get(f"/data/{record_id}/{bulk_id}")
    assert get_record_data_response.status_code == 200, get_record_data_response.text

    _result_df = pd.read_parquet(BytesIO(get_record_data_response.content))

    expected_dtypes = pd.Series(
        {
            "int-A": "int64",
            "float-B": "float64",
            "bool-D": "bool",
            "date": "datetime64[ns]",
            "modified": "datetime64[ns, pytz.FixedOffset(120)]",
            "string-G": "object",
        }
    )
    # sort to get same order that _result_df dataframe.
    expected_dtypes.sort_index(inplace=True)

    pd.testing.assert_series_equal(_result_df.dtypes, expected_dtypes)
