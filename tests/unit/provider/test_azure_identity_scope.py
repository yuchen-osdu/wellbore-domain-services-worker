from types import SimpleNamespace

import pytest

from osdu_az.identity import az_identity


@pytest.mark.asyncio
async def test_aad_client_id_is_converted_to_an_oauth_scope(monkeypatch):
    class FakeSecretClient:
        def __init__(self, vault_url, credential):
            assert vault_url == "https://example.vault.azure.net/"
            assert credential is fake_credential

        async def get_secret(self, name):
            assert name == "aad-client-id"
            return SimpleNamespace(value="api://osdu")

    fake_credential = object()
    monkeypatch.setattr(az_identity.conf, "keyvault_url", "https://example.vault.azure.net/")
    monkeypatch.setattr(az_identity, "SecretClient", FakeSecretClient)
    monkeypatch.setattr(
        az_identity.AzureIdentity,
        "get_default_credential",
        staticmethod(lambda: fake_credential),
    )

    assert await az_identity.AzureIdentity.get_resource_id() == "api://osdu/.default"
