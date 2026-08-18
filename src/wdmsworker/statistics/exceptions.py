class ComputationRunningError(Exception):
    """Raised if computation of bulk statistics are already running"""


class RequestedCurvesError(Exception):
    """Raised if requested curves don't exist in associated WellLog"""

    public_error_type = "CURVES_NOT_FOUND"


class StatisticsNotFoundError(Exception):
    """Raised if requested bulk statistics does not exist"""

    public_error_type = "DATA_NOT_FOUND"


class ComputationNotCompleteError(Exception):
    """Raised if computation of requested bulk statistics is not finished yet"""

    public_error_type = "COMPUTATION_NOT_COMPLETE"


class BulkCatalogNotFoundError(Exception):
    """Raised if requested record_id and bulk_id does not have bulk catalog"""

    public_error_type = "BULK_CATALOG_NOT_FOUND"
