from types import ModuleType
from fastapi import FastAPI


def initialize_for_provider(provider: str, app: FastAPI) -> ModuleType:
    """
    lookup for the module corresponding to the provider name/short name given in parameter and
    call `initialize_provider`.
    :param provider: provider short name
    :param app:
    :return: provider module
    :raise: `ModuleNotFoundError` if not module found for the given provider
    """
    if provider == "az":
        from . import azure

        provider_module = azure  # type: ignore
    elif provider == "ibm":
        from . import ibm

        provider_module = ibm  # type: ignore
    elif provider == "gc":
        from . import gc

        provider_module = gc  # type: ignore
    elif provider == "baremetal":
        from . import baremetal

        provider_module = baremetal  # type: ignore
    elif provider == "local":
        from . import local

        provider_module = local  # type: ignore
    else:
        raise ModuleNotFoundError(f"provider {provider} not supported")

    provider_module.initialize_provider(app)

    # check dependencies are setup
    if app.state.blob_storage is None:  # might be better to check 'isinstance(app.state.blob_storage, BlobStorageBase)'
        raise NotImplementedError(f"provider {provider} do not implement blob storage dependency")
    if app.state.get_tenant is None:
        raise NotImplementedError(f"provider {provider} do not implement get tenant dependency")
    return provider_module
