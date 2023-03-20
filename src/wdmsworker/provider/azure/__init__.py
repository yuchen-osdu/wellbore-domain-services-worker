from osdu_az.storage.blob_storage_az import AzureAioBlobStorage
from osdu.core.api.storage.tenant import Tenant
from .logger import init_logger
from ...logger import set_logger


def initialize_for_azure(app):
    app.state.logger = init_logger(service_name="os-wellbore-ddms-worker")

    set_logger(app.state.logger)

    app.state.blob_storage = AzureAioBlobStorage()
    app.state.get_tenant = lambda dp: Tenant(data_partition_id=dp, project_id="", bucket_name="wdms-osdu")
