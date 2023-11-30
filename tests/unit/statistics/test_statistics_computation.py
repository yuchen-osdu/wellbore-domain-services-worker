import io

import numpy as np
import pandas as pd
import pytest
from unittest import mock

from osdu.core.api.storage.blob_storage_base import BlobStorageBase

from ..bulk.reader_test import split_bulk_into_chunk, store_chunks

from wdmsworker.bulk.catalog import async_save_bulk_catalog_with_blob_storage
from wdmsworker.statistics.bulk_statistics import BulkStatistics
from wdmsworker.statistics.exceptions import BulkCatalogNotFoundError


def _add_nan_values_in_df(chunk_df):
    cols_with_nan = [c for c in chunk_df.columns if c.endswith("nan")]
    for col_with_nan in cols_with_nan:
        chunk_df.loc[chunk_df.sample(frac=0.1).index, col_with_nan] = np.nan


def _create_multi_types_df(values_count):
    return pd.DataFrame({
        "int-A": np.arange(-100, 400, step=1, dtype=int),
        "int-A-nan": np.arange(-100, 1400, step=3, dtype=int),
        "float-B": np.arange(-100, 650, step=1.5, dtype=float),
        "float-B-nan": np.arange(-100, 1550, step=3.3, dtype=float),
        "date-C": pd.date_range(start="1/1/2022", freq="s", periods=values_count),
        "date-C-nan": pd.date_range(start="1/1/2022", freq="D", periods=values_count),
        "bool-D": [i % 2 == 0 for i in range(values_count)],
        "string-E": [f"string_value_{i}" for i in range(values_count)],
    })


def test_compute_statistics_batch():
    stats_computer = BulkStatistics(storage=mock.AsyncMock(), tenant=mock.AsyncMock())

    values_count = 500
    bulk_catalog = mock.Mock()
    bulk_catalog.nb_rows = values_count

    bulk_df = _create_multi_types_df(values_count)
    _add_nan_values_in_df(bulk_df)

    computed_stats_df = stats_computer._compute_statistics_batch(bulk_df, bulk_catalog)

    expected_stats_df = bulk_df.describe(datetime_is_numeric=True, percentiles=[0.10, 0.5, 0.90])
    expected_stats_df = expected_stats_df.astype("string").transpose()
    expected_stats_df["totalCount"] = str(values_count)
    expected_stats_df.rename(columns={"count": "nonAbsentValuesCount"}, inplace=True)

    pd.testing.assert_frame_equal(computed_stats_df, expected_stats_df, check_like=True)


@pytest.mark.anyio
async def test_save_statistics():
    stats_computer = BulkStatistics(storage=mock.AsyncMock(), tenant=mock.AsyncMock())

    values_count = 500
    bulk_catalog = mock.Mock()
    bulk_catalog.nb_rows = values_count

    bulk_df = _create_multi_types_df(values_count)
    _add_nan_values_in_df(bulk_df)

    computed_stats_df = stats_computer._compute_statistics_batch(bulk_df, bulk_catalog)

    await stats_computer._save_statistics_batch(
        df_statistics=computed_stats_df,
        record_id="my_record_id",
        bulk_id="my_bulk_id",
    )
    assert stats_computer._storage.upload.called
    called_tenant, save_file_path, parquet_bytes_io = stats_computer._storage.upload.call_args[0]

    assert called_tenant == stats_computer._tenant
    assert (
        save_file_path
        == "3241e4363e7da3b88cb0f654e32b043df6c83a59/bulk/my_bulk_id/statistics.v1"
        "/data/statistics_b51f28649a-a2eb034916.parquet"
    )
    assert (
        parquet_bytes_io.read() == io.BytesIO(computed_stats_df.to_parquet(None, index=True, engine="pyarrow")).read()
    )


@pytest.mark.anyio
async def test_statistics_fetch_data(bulk_storage_mock: BlobStorageBase, test_tenant):
    reference_df, chunk_groups = split_bulk_into_chunk("no_split")
    catalog = await store_chunks(
        bulk_storage_mock, test_tenant, chunk_groups, within_session=False, record_id="rid", bulk_id="bid"
    )
    catalog.nb_rows = len(reference_df.index)
    bulk_stats_computer = BulkStatistics(storage=bulk_storage_mock, tenant=test_tenant)

    fetched_df = await bulk_stats_computer._fetch_bulk_batch(
        catalog=catalog, columns=tuple(sorted(catalog.all_columns))
    )
    pd.testing.assert_frame_equal(reference_df, fetched_df)


@pytest.mark.anyio
async def test_statistics_compute_and_get_data(bulk_storage_mock: BlobStorageBase, test_tenant):
    #
    reference_df, chunk_groups = split_bulk_into_chunk("no_split")
    catalog = await store_chunks(
        bulk_storage_mock, test_tenant, chunk_groups, within_session=False, record_id="rid", bulk_id="bid"
    )
    catalog.nb_rows = len(reference_df.index)
    bulk_stats_computer = BulkStatistics(storage=bulk_storage_mock, tenant=test_tenant)

    # required to trigger the computation
    await async_save_bulk_catalog_with_blob_storage(bulk_storage_mock, test_tenant, "bid", catalog)
    await bulk_stats_computer.compute_bulk_statistics(record_id="rid", bulk_uri="bid", record_version=12345)

    all_expected_cols = ["A", "B", "C", "D", "E", "F[0]", "F[1]"]
    # verify if "curves_selection == None" or "curves_selection == all columns" has the same behavior
    for curve_selection in [sorted(catalog.all_columns), None]:
        stats_df, stats_meta = await bulk_stats_computer.get_bulk_statistics(
            record_id="rid",
            bulk_uri="bid",
            curves_selection=curve_selection,
        )
        assert sorted(stats_df.index) == all_expected_cols
        assert stats_df.shape == (7, 9)

    sub_stats_df, sub_stats_meta = await bulk_stats_computer.get_bulk_statistics(
        record_id="rid",
        bulk_uri="bid",
        curves_selection=["A", "B", "C"],
    )
    assert list(sub_stats_df.index) == ["A", "B", "C"]
    assert sub_stats_df.shape == (3, 9)


@pytest.mark.anyio
async def test_compute_statistics_no_catalog(bulk_storage_mock: BlobStorageBase, test_tenant):
    reference_df, chunk_groups = split_bulk_into_chunk("no_split")
    catalog = await store_chunks(
        bulk_storage_mock, test_tenant, chunk_groups, within_session=False, record_id="rid", bulk_id="bid"
    )
    catalog.nb_rows = len(reference_df.index)
    bulk_stats_computer = BulkStatistics(storage=bulk_storage_mock, tenant=test_tenant)

    with pytest.raises(BulkCatalogNotFoundError):
        await bulk_stats_computer.compute_bulk_statistics(record_id="rid", bulk_uri="bid", record_version=123456)

    with pytest.raises(BulkCatalogNotFoundError):
        await bulk_stats_computer.get_bulk_statistics(record_id="rid", bulk_uri="bid", curves_selection=None)
