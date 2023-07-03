# TODO [TAG pandas dependent]
import pandas as pd
import pytest

from wdmsworker.model.describe import ColumnDescribe

from ..generate_data import generate_df


def test_original_df_should_not_be_altered_when_described():
    df = generate_df([f"col_{x}" for x in range(10)], range(20))
    original_df = df.copy()
    ColumnDescribe.from_column(df, "col_1")
    pd.testing.assert_frame_equal(df, original_df)

    ColumnDescribe.from_column(df, "col_1", "col_0")
    pd.testing.assert_frame_equal(df, original_df)


@pytest.mark.parametrize("column_label", ("MD", "", None))
def test_column_describe_empty_dataframe(column_label):
    describe = ColumnDescribe.from_column(pd.DataFrame(), column_label)
    assert describe.start_end_df().empty
    assert describe.name == "_wdms_index_"


def test_index_describe_empty_dataframe():
    desc = ColumnDescribe.from_index(pd.DataFrame())
    assert desc.start_end_df().empty


def test_column_describe_unknown_column():
    df = generate_df(["GR", "DEN"], range(3))

    # WHEN reference is not in the df
    desc = ColumnDescribe.from_column(df, "GR", "MD")
    # THEN its ignored
    assert desc.name == "GR"
    assert "GR" in desc.start_end_df()

    # WHEN neither the requested column nor the reference is in the df
    desc = ColumnDescribe.from_column(df, "CAL", "MD")
    # THEN only index is used to construct
    assert desc.name == "_wdms_index_"
    assert len(desc.start_end_df()) == 2
