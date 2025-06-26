from enum import Enum
from typing import Dict

from pydantic import BaseModel, Field
from datetime import datetime


class BulkStatisticsStatus(str, Enum):
    """Status available for computation of bulk data statistics"""

    Error = "error"
    Started = "started"
    Running = "running"
    Complete = "complete"


class StatisticsComputationMeta(BaseModel):
    """Meta data of computation for bulk data statistics"""

    computation_start_datetime: datetime = Field(
        title="Statistics computation start datetime in ISO format", alias="computationStartDatetime"
    )
    record_id: str = Field(alias="recordId")
    record_version: int = Field(alias="recordVersion")
    computation_status: BulkStatisticsStatus = Field(alias="computationStatus")


class InternalStatisticsComputationMeta(BaseModel):
    meta: StatisticsComputationMeta
    computation_attempt: int = Field(alias="computationAttempt")
    last_computation_date: datetime = Field(
        title="Datetime of last computation run. Internal usage", alias="lastComputationDate"
    )


class CurveStatistics(BaseModel):
    mean: str = Field(title="Mean value")
    std: str = Field(title="Standard deviation value")
    min: str = Field(title="Minimum value")
    p_10: str = Field(alias="10%", title="10th percentiles")
    p_50: str = Field(alias="50%", title="50th percentiles")
    p_90: str = Field(alias="90%", title="90th percentiles")
    max: str = Field(title="Maximum value")
    total_count: str = Field(title="Number of values in the curve", alias="totalCount")
    non_absent_values_count: str = Field(title="Number of valid values in the curve", alias="nonAbsentValuesCount")


class BulkDataStatisticsResponse(StatisticsComputationMeta):
    """Response for bulk data statistics and its meta-data"""

    data: Dict[str, CurveStatistics] = Field(
        title="Curves statistics' values",
        examples=[
            {
                "CurveName": CurveStatistics(
                    **{
                        "mean": "450.8438",
                        "std": "318.27778186518816",
                        "min": "-100.0",
                        "10%": "9.0",
                        "50%": "451.0",
                        "90%": "893.0",
                        "max": "999.0",
                        "totalCount": "100000",
                        "nonAbsentValuesCount": "100000.0",
                    }
                )
            }
        ],
    )

    class Config:
        json_schema_extra = {
            "example": {
                "computationStartDatetime": "2022-05-18T16:22:16.010582",
                "recordId": "osdu:work-product-component--WellLog:6d9c95c972254bbbaeaecbfa67fd1cf3",
                "recordVersion": "1998222529528913770053504387865218642",
                "computationStatus": "complete",
                "data": {
                    "ARR[0]": {
                        "mean": "450.8438",
                        "std": "318.27778186518816",
                        "min": "-100.0",
                        "10%": "9.0",
                        "50%": "451.0",
                        "90%": "893.0",
                        "max": "999.0",
                        "totalCount": "100000",
                        "nonAbsentValuesCount": "100000.0",
                    },
                    "ARR[1]": {
                        "mean": "448.06855",
                        "std": "316.8023859891449",
                        "min": "-100.0",
                        "10%": "10.0",
                        "50%": "446.0",
                        "90%": "889.0",
                        "max": "999.0",
                        "totalCount": "100000",
                        "nonAbsentValuesCount": "100000.0",
                    },
                    "ARR[2]": {
                        "mean": "451.01309",
                        "std": "317.40833668820653",
                        "min": "-100.0",
                        "10%": "11.0",
                        "50%": "453.0",
                        "90%": "890.0",
                        "max": "999.0",
                        "totalCount": "100000",
                        "nonAbsentValuesCount": "100000.0",
                    },
                    "ARR[3]": {
                        "mean": "449.16661",
                        "std": "317.7767589547625",
                        "min": "-100.0",
                        "10%": "8.900000000001455",
                        "50%": "450.0",
                        "90%": "890.0",
                        "max": "999.0",
                        "totalCount": "100000",
                        "nonAbsentValuesCount": "100000.0",
                    },
                },
            }
        }
