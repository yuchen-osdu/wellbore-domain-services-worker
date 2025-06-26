from io import BytesIO, StringIO
from functools import reduce
from itertools import product
import uuid
from typing import List, Dict, Tuple

import numpy as np
import pandas as pd
import pytest

from .generate_data import generate_df, generate_df_dtype, assert_frame_equal


@pytest.fixture
def record_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def session_id() -> str:
    return str(uuid.uuid4())


format_params = [
    pytest.param("application/x-parquet", id="parquet"),
    pytest.param("application/json", id="json"),
]

session_modes = [
    "overwrite",
    "update",
]


@pytest.mark.parametrize("content_type_header", format_params)
@pytest.mark.parametrize("accept_content", format_params)
@pytest.mark.parametrize(
    "columns",
    [
        ["MD", "X"],
        ["float_MD", "float_X"],
        ["str_MD", "str_X"],
        ["date_MD", "date_X"],
        ["MD", "date_X", "float_X", "str_X"],
    ],
)
def test_send_all_data_once(test_client, record_id: str, columns, content_type_header: str, accept_content: str):
    initial_data_df = generate_df(columns, range(5, 13))
    data_to_send = _df_to_format(initial_data_df, content_type_header)
    headers = {"content-type": content_type_header}

    get_response_no_data = test_client.get(f"/data/{record_id}/unknown_id", headers={"accept": accept_content})
    assert get_response_no_data.status_code == 404

    response = test_client.post(f"/data/{record_id}", data=data_to_send, headers=headers)
    assert response.status_code == 200
    response_obj = response.json()
    bulk_id = response_obj["bulkid"]

    get_response = test_client.get(f"/data/{record_id}/{bulk_id}", headers={"accept": accept_content})
    assert get_response.status_code == 200
    result_df = _create_df_from_response(get_response)

    if content_type_header.endswith("parquet") and not accept_content.endswith("parquet"):
        result_df = _cast_datetime_to_datetime64_ns(result_df)

    if content_type_header.endswith("json"):
        initial_data_df = pd.read_json(StringIO(data_to_send), orient="split")

    assert_dataframe_equal(initial_data_df, result_df)


@pytest.mark.parametrize("content_type_header", format_params)
@pytest.mark.parametrize("accept_content", format_params)
@pytest.mark.parametrize(
    "columns",
    [
        ["float_MD", "float_X"],
        ["str_MD", "str_X"],
        ["date_MD", "date_X"],
        ["TVD", "float_X", "str_X", "date_X"],
        ["MD", "X"],
        ["MD", "float_X"],
        ["MD", "str_MD"],
        ["MD", "date_X"],
        ["MD", "float_X", "str_X", "date_X"],
    ],
)
@pytest.mark.parametrize("session_mode", session_modes)
def test_overwrite_data_by_chunk_append(
    test_client,
    record_id: str,
    session_id: str,
    session_mode: str,
    columns: List[str],
    content_type_header: str,
    accept_content: str,
):
    """Create session, append chunking with consecutive index, validate session"""
    reference = "MD" if "MD" in columns else None
    initial_df = generate_df(["MD", "X"], range(5), reference)

    response = test_client.post(
        f"/data/{record_id}",
        data=_df_to_format(initial_df, content_type_header),
        headers={"Content-Type": content_type_header},
    )
    assert response.status_code == 200
    response_obj = response.json()
    bulk_id = response_obj["bulkid"]

    get_response = test_client.get(f"/data/{record_id}/{bulk_id}")
    assert get_response.status_code == 200
    initial_bulk_data = _create_df_from_response(get_response)
    assert initial_bulk_data.shape == initial_df.shape, "existing bulk data should not be empty"

    bulk_id, describe, chunk_dfs = _send_chunks_and_commit(
        test_client,
        [(columns, range(5, 10)), (columns, range(10, 15))],
        record_id,
        session_id,
        content_type_header,
        session_mode,
        previous_bulk=bulk_id,
        reference=reference,
    )

    get_response = test_client.get(f"/data/{record_id}/{bulk_id}", headers={"accept": accept_content})
    assert get_response.status_code == 200
    df = _create_df_from_response(get_response)

    if session_mode == "update":
        chunk_dfs.insert(0, initial_df)

    expected = pd.concat(chunk_dfs, axis=0)
    df = _cast_datetime_to_datetime64_ns(df)

    sorted_columns = sorted(columns)
    df = df[sorted_columns]
    expected = expected[sorted_columns]
    pd.testing.assert_frame_equal(
        df,
        expected,
        check_dtype=False,
        check_column_type=False,
        check_datetimelike_compat=True,
    )


@pytest.mark.parametrize("data_format", format_params)
def test_add_curve_by_chunk_different_cols(test_client, record_id: str, session_id: str, data_format: str):
    bulk_id, describe, with_new_col = _post_chunk_then_commit_then_get(
        test_client,
        [(["MD", "X"], range(5, 20)), (["Y"], range(5, 20)), (["Z"], range(5, 20))],
        record_id,
        session_id,
        data_format,
        "overwrite",
        "MD",
    )
    assert set(with_new_col.columns) == {"MD", "X", "Y", "Z"}
    assert with_new_col.shape == (15, 4)
    assert with_new_col.index.tolist() == list(range(5, 20))
    assert describe["reference"]["name"] == "MD"


@pytest.mark.parametrize("data_format", format_params)
def test_add_curve_by_chunk_same_cols(test_client, record_id: str, session_id: str, data_format: str):
    bulk_id, describe, with_new_col = _post_chunk_then_commit_then_get(
        test_client,
        [(["X"], range(10)), (["X"], range(10, 20)), (["X"], range(20, 30))],
        record_id,
        session_id,
        data_format,
        "overwrite",
    )
    assert list(with_new_col.columns) == ["X"]
    assert with_new_col.index.tolist() == list(range(30))


@pytest.mark.parametrize("session_mode", session_modes)
def test_session_commit_no_data(test_client, record_id: str, session_id: str, session_mode: str):
    """Create session, append chunking with overlapped index, validate session"""
    commit_response = test_client.patch(f"/data/{record_id}/session/{session_id}?completion={session_mode}")
    assert commit_response.status_code == 422
    assert commit_response.json()["errorType"] == "NO_DATA_TO_COMMIT"


@pytest.mark.parametrize("data_format", format_params)
@pytest.mark.parametrize(
    "columns_name",
    [
        list(map(lambda x: f"test[{x}]", range(100))),
        list(map(lambda x: f"{x[0]}_test[{x[1]}]", product(range(10), repeat=2))),
    ],
)
def test_nat_sort_columns(test_client, record_id: str, session_id: str, data_format: str, columns_name):
    # nat sort is only triggers on array curves
    _, _, response_df = _post_chunk_then_commit_then_get(
        test_client,
        [(columns_name[:10], range(20)), (columns_name[10:], range(20))],
        record_id,
        session_id,
        data_format,
        "overwrite",
    )
    assert list(response_df.columns) == columns_name


def test_too_many_values_requested(test_client, record_id: str, session_id: str):
    row_count = 3_400_000
    bulk_id, _, _ = _send_chunks_and_commit(
        test_client,
        [(["A"], range(row_count)), (["B"], range(row_count)), (["C"], range(row_count))],
        record_id,
        session_id,
        "application/parquet",
        "overwrite",
    )

    # WHEN read all
    response = test_client.get(
        f"/data/{record_id}/{bulk_id}",
        headers={"accept": "application/parquet"},
    )
    assert response.status_code == 413
    response_json = response.json()
    assert response_json["message"]
    assert response_json["errorType"] == "READ_REQUEST_TOO_LARGE"
    assert response_json["bulkDescription"]["totalNumberOfRows"] == row_count
    assert response_json["bulkDescription"]["totalNumberOfColumns"] == 3
    assert response_json["limits"]["values"] == 10_000_000
    assert response_json["limits"]["columns"] == 3_000

    curves_set = sorted(p["curves"][0] for p in response_json["bulkDescription"]["partitions"])
    assert curves_set == ["A", "B", "C"]


def test_too_many_values_requested_workflow(test_client, record_id: str, session_id: str):
    bulk_id, _, expected_dfs = _send_chunks_and_commit(
        test_client,
        [(["x", "y"], [0, 1]), ([f"A[{i}]" for i in range(2500)], [0, 1]), ([f"B[{i}]" for i in range(2500)], [0, 1])],
        record_id,
        session_id,
        "application/parquet",
        "overwrite",
    )

    expected_df = pd.concat(expected_dfs, axis=1)

    # WHEN read all
    response = test_client.get(
        f"/data/{record_id}/{bulk_id}",
        headers={"accept": "application/parquet"},
    )
    assert response.status_code == 413
    response_json = response.json()
    assert response_json["bulkDescription"]["totalNumberOfRows"] == 2
    assert response_json["bulkDescription"]["totalNumberOfColumns"] == 5_002

    dfs = []
    for c in (p["curves"] for p in response_json["bulkDescription"]["partitions"]):
        data_response = test_client.get(f"/data/{record_id}/{bulk_id}", params={"curves": ",".join(c)})
        assert data_response.status_code == 200
        dfs.append(_create_df_from_response(data_response))

    assert_frame_equal(expected_df, pd.concat(dfs, axis=1), check_column_order=False)


def test_reference_not_exist_in_bulk(test_client, record_id: str, session_id: str):
    row_count = 3
    _send_chunks_and_commit(
        test_client,
        [(["A"], range(row_count)), (["B", "C"], range(row_count))],
        record_id,
        session_id,
        "application/parquet",
        "overwrite",
        "MD",
        expected_status=422,
    )


def test_reference_not_cover_all_bulk_index(test_client, record_id: str, session_id: str):
    row_count = 3
    _send_chunks_and_commit(
        test_client,
        [(["MD"], range(row_count - 1)), (["B", "C"], range(row_count))],
        record_id,
        session_id,
        "application/parquet",
        "overwrite",
        "MD",
        expected_status=422,
    )


def test_two_sessions_with_different_format(test_client, record_id: str, session_id: str):
    session_id1, session_id2 = session_id[:-1] + "1", session_id[:-1] + "2"
    row_count = 5
    previous_bulk_id, _, _ = _send_chunks_and_commit(
        test_client,
        [(["A"], range(row_count))],
        record_id,
        session_id1,
        "application/json",
        "overwrite",
    )
    _, describe, df = _post_chunk_then_commit_then_get(
        test_client,
        [(["B"], range(row_count)), (["C"], range(row_count))],
        record_id,
        session_id2,
        "application/parquet",
        "update",
        None,
        previous_bulk_id,
    )

    assert df.index.tolist() == list(range(row_count))
    assert set(df.columns) == set(describe["curves"].keys())
    assert describe["rowCount"] == row_count
    ref_describe = describe["reference"]
    assert ref_describe["startEnd"]["index"] == [0, 4]
    assert describe["curves"] == {"A": 1, "B": 1, "C": 1}


def test_same_session_with_different_format(test_client, record_id: str, session_id: str):
    _send_chunk(
        test_client, f"/data/{record_id}/session/{session_id}", generate_df(["A"], range(5)), "application/json"
    )
    _send_chunk(
        test_client, f"/data/{record_id}/session/{session_id}", generate_df(["A"], range(5, 10)), "application/parquet"
    )
    commit_response = test_client.patch(f"/data/{record_id}/session/{session_id}", params={"completion": "overwrite"})
    assert commit_response.status_code == 200
    bulk_id = commit_response.json()["bulkid"]
    data_response = test_client.get(f"/data/{record_id}/{bulk_id}", headers={"accept": "application/parquet"})

    assert data_response.status_code == 200
    df = _create_df_from_response(data_response)
    assert len(df) == 10


def test_add_curve_by_chunk_overlap_different_cols(test_client, record_id: str, session_id: str):
    """Create session, append chunking with consecutive index, validate session"""
    _, _, df = _post_chunk_then_commit_then_get(
        test_client,
        [
            (["MD", "A"], range(5, 10)),
            (["B"], range(8)),  # overlap left side
            (["C"], range(8, 15)),  # overlap left side
            (["D"], range(6, 8)),  # within
            (["E"], range(15)),
        ],  # overlap both side
        record_id,
        session_id,
        "application/parquet",
        "overwrite",
    )
    assert set(df.columns) == {"A", "B", "C", "D", "E", "MD"}
    assert df.shape == (15, 6)


def test_add_curve_by_chunk_misaligned_columns(test_client, record_id: str, session_id: str):
    """Create session, append chunking with consecutive index, validate session"""
    _, _, df = _post_chunk_then_commit_then_get(
        test_client,
        [
            (["MD", "A"], range(5, 10)),
            (["B", "C"], range(8)),  # overlap left side
            (["C"], range(8, 15)),  # overlap left side
        ],  # overlap both side
        record_id,
        session_id,
        "application/parquet",
        "overwrite",
    )
    assert set(df.columns) == {"A", "B", "C", "MD"}
    assert df.shape == (15, 4)


def test_session_sent_same_col_different_types(test_client, record_id, session_id):
    _send_chunks_and_commit(
        test_client,
        [
            ({"MD": "int", "A": "float"}, range(5, 10)),
            ({"MD": "int", "A": "int"}, range(15, 19)),
        ],
        record_id,
        session_id,
        "application/parquet",
        "overwrite",
        expected_status=422,
    )


def test_add_curve_by_chunk_same_cols_overlapped_index(test_client, record_id, session_id):
    """Create session, append chunking with consecutive index, validate session"""

    data_format = "application/parquet"
    bulk_id, _, chunk_dfs = _send_chunks_and_commit(
        test_client,
        [(["MD", "X"], range(20)), (["MD", "X"], range(10, 30)), (["MD", "X"], range(25, 40))],
        record_id,
        session_id,
        data_format,
        "overwrite",
    )

    data_response = test_client.get(f"/data/{record_id}/{bulk_id}", headers={"accept": data_format})

    assert data_response.status_code == 200
    result_df = _create_df_from_response(data_response)

    chunk_1, chunk_2, chunk_3 = chunk_dfs
    # non overlaping ranges
    assert result_df.loc[0:9].compare(chunk_1.loc[0:9]).empty
    assert result_df.loc[21:24].compare(chunk_2.loc[21:24]).empty
    assert result_df.loc[30:39].compare(chunk_3.loc[30:39]).empty

    # overlaping ranges are either from one chunk or the other since
    # order is not guaranteed
    assert (
        result_df.loc[10:19].compare(chunk_1.loc[10:19]).empty or result_df.loc[10:19].compare(chunk_2.loc[10:19]).empty
    )
    assert (
        result_df.loc[25:29].compare(chunk_3.loc[25:29]).empty or result_df.loc[25:29].compare(chunk_2.loc[25:29]).empty
    )


@pytest.mark.parametrize(
    "version_data",
    (
        [
            (["MD", "X", "Y"], range(5)),
            (["A"], range(5)),
            (["C", "B"], range(5)),
        ],
        [
            (["MD", "X", "Y"], range(5)),
            (["MD", "X", "Y"], range(5, 10)),
            (["MD", "X", "Y"], range(10, 15)),
        ],
        [
            (["MD", "X", "Y"], range(5)),
            (["MD", "X", "Z"], range(5)),
            (["MD", "A", "B"], range(5)),
            (["MD", "Y", "Z"], range(5)),
            (["MD", "A", "B", "X", "Z"], range(5)),
        ],
        [
            (["MD", "X", "Y"], range(15)),
            (["MD", "X", "Y"], range(5, 10)),
            (["MD", "Y", "X"], range(10, 20)),
        ],
    ),
    ids=["add_columns", "add_rows", "column_overlap", "index_overlap"],
)
def test_session_update_previous_version(test_client, record_id, session_id, version_data):
    """create a session update on a previous version"""
    data_format = "application/parquet"

    previous_bulk_id = None
    version_dfs = []
    for i, data in enumerate(version_data):
        mode = "update" if previous_bulk_id else "overwrite"
        previous_bulk_id, describe, chunk_dfs = _send_chunks_and_commit(
            test_client, [data], record_id, session_id + str(i), data_format, mode, previous_bulk=previous_bulk_id
        )
        version_dfs.extend(chunk_dfs)

        expected_df = reduce(lambda previous_bulk, latest_bulk: latest_bulk.combine_first(previous_bulk), version_dfs)

        data_response = test_client.get(f"/data/{record_id}/{previous_bulk_id}", headers={"accept": data_format})
        actual_df = _create_df_from_response(data_response)

        # as column order might not to be the same
        assert set(actual_df.columns.tolist()) == set(expected_df.columns.tolist())
        actual_df = actual_df[expected_df.columns.tolist()]
        pd.testing.assert_frame_equal(actual_df, expected_df)


@pytest.mark.parametrize(
    "version_data",
    (
        # list of columns, index, reference values. The first is used as previous bulk
        [
            (["MD", "X", "Y"], range(5), range(5)),
            (["A"], range(5, 10), None),
            (["MD", "Y"], range(6, 10), range(6, 10)),  # MD value missing at index=5
        ],
        [
            (["MD", "X", "Y"], range(5), range(5)),
            (["MD", "X", "Y"], range(5, 10), range(4, 9)),  # 4 will be repeated against previous
            (["MD", "X", "Y"], range(10, 15), range(10, 15)),
        ],
    ),
    ids=["missing", "duplicate"],
)
def test_session_update_previous_version_invalid_reference(test_client, record_id, session_id, version_data):
    """create a session update on a previous version"""
    data_format = "application/parquet"

    def _make_df(version_data_input):
        cols, index, ref_values = version_data_input
        result_df = generate_df(cols, index)
        if "MD" in result_df and ref_values:
            result_df["MD"] = list(ref_values)
        return result_df

    previous_chunks = [_make_df(version_data[0])]
    previous_bulk_id, _, _ = _send_chunks_and_commit(
        test_client, None, record_id, session_id + "P", data_format, "overwrite", reference="MD", chunks=previous_chunks
    )

    chunks = [_make_df(d) for d in version_data[1:]]

    _send_chunks_and_commit(
        test_client,
        None,
        record_id,
        session_id,
        data_format,
        "update",
        reference="MD",
        previous_bulk=previous_bulk_id,
        expected_status=422,
        chunks=chunks,
    )


# ---------------------------------------------------------------
# ---------------------------------------------------------------
# ---------------------------------------------------------------
# ----------------------------- TOOLING -------------------------
# ---------------------------------------------------------------
# ---------------------------------------------------------------
# ---------------------------------------------------------------


def _create_df_from_response(response) -> pd.DataFrame:
    content = BytesIO(response.content)
    content.seek(0)

    content_type = response.headers.get("content-type")
    if "parquet" in content_type:
        return pd.read_parquet(content)
    elif "json" in content_type:
        return pd.read_json(path_or_buf=content, orient="split", convert_axes=False).replace("NaN", np.nan)
    else:
        raise ValueError(f"Unknown content-type: '{content_type}'")


def _df_to_format(df: pd.DataFrame, data_format) -> bytes | str | None:
    if "parquet" in data_format:
        return df.to_parquet(engine="pyarrow")
    elif "json" in data_format:
        return df.to_json(orient="split", date_format="iso")
    else:
        raise ValueError(f"Unknown content-type: '{data_format}'")


def _cast_datetime_to_datetime64_ns(result_df: pd.DataFrame) -> pd.DataFrame:
    """if datetime is detected, cast data column as datetime to ensure date values are valid"""
    for name, _col in result_df.items():
        if name.startswith("date"):
            result_df[name] = result_df[name].astype("datetime64[ns]")

    return result_df


def assert_dataframe_equal(left_df, right_df):
    assert left_df.index.dtype == right_df.index.dtype
    assert left_df.shape == right_df.shape
    pd.testing.assert_frame_equal(
        left_df,
        right_df,
        check_dtype=False,
        check_column_type=False,
        check_datetimelike_compat=True,
        # because internal of index name that may be different but its internal mechanism only
        check_names=False,
    )


def _post_chunk_then_commit_then_get(
    test_client,
    cols_ranges,
    record_id: str,
    session_id: str,
    data_format: str,
    session_mode: str,
    reference: str | None = None,
    previous_bulk: str | None = None,
) -> Tuple[str, Dict, pd.DataFrame]:
    bulk_id, describe, _ = _send_chunks_and_commit(
        test_client,
        cols_ranges,
        record_id,
        session_id,
        data_format,
        session_mode,
        reference,
        previous_bulk,
    )

    data_response = test_client.get(f"/data/{record_id}/{bulk_id}", headers={"accept": data_format})

    assert data_response.status_code == 200
    df = _create_df_from_response(data_response)
    return bulk_id, describe, df


def _send_chunk(test_client, url, chunk_df, data_format, reference: str | None = None):
    params = {"reference": reference} if reference else None
    headers = {"Content-Type": data_format}
    chunk_response = test_client.post(url, data=_df_to_format(chunk_df, data_format), headers=headers, params=params)
    assert chunk_response.status_code == 200


def _generate_chunk(cols_with_ranges, reference: str | None = None):
    for columns, ranges in cols_with_ranges:
        if isinstance(columns, dict):
            yield generate_df_dtype(columns, ranges, reference)
        else:
            yield generate_df(columns, ranges, reference)


def _send_chunks_and_commit(
    test_client,
    cols_ranges,
    record_id: str,
    session_id: str,
    data_format: str,
    session_mode: str,
    reference: str | None = None,
    previous_bulk: str | None = None,
    *,
    expected_status: int = 200,
    chunks: List[pd.DataFrame] | None = None,
) -> Tuple[str, Dict, List[pd.DataFrame]]:
    """Create session, add chunks with given columns and index, validate the session"""
    created_dfs = []

    if not chunks:
        chunks = _generate_chunk(cols_ranges, reference)

    for chunk_df in chunks:
        created_dfs.append(chunk_df)
        _send_chunk(test_client, f"/data/{record_id}/session/{session_id}", chunk_df, data_format, reference)

    params = {"completion": session_mode}
    if reference:
        params["reference"] = reference
    if previous_bulk:
        params["from_bulk"] = previous_bulk
    commit_response = test_client.patch(f"/data/{record_id}/session/{session_id}", params=params)
    assert commit_response.status_code == expected_status
    if expected_status > 299:
        return "", {}, []

    response_obj = commit_response.json()
    return response_obj["bulkid"], response_obj["describe"], created_dfs
