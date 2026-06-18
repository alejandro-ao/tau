import pytest

from tau_ai import OpenAICodexProvider
from tau_coding import provider_runtime
from tau_coding.credentials import FileCredentialStore, OAuthCredential
from tau_coding.provider_config import OpenAICodexProviderConfig
from tau_coding.provider_runtime import OpenAICodexCredentialResolver, create_model_provider


def test_create_model_provider_returns_openai_codex_provider(tmp_path) -> None:
    store = FileCredentialStore(tmp_path / "credentials.json")

    provider = create_model_provider(
        OpenAICodexProviderConfig(),
        credential_store=store,
    )

    assert isinstance(provider, OpenAICodexProvider)


@pytest.mark.anyio
async def test_openai_codex_credential_resolver_refreshes_expired_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = FileCredentialStore(tmp_path / "credentials.json")
    store.set_oauth(
        "openai-codex",
        OAuthCredential(
            access="old-access",
            refresh="old-refresh",
            expires=1,
            account_id="old-account",
        ),
    )

    async def fake_refresh(refresh_token: str) -> OAuthCredential:
        assert refresh_token == "old-refresh"
        return OAuthCredential(
            access="new-access",
            refresh="new-refresh",
            expires=9999999999999,
            account_id="new-account",
        )

    monkeypatch.setattr(provider_runtime, "refresh_openai_codex_token", fake_refresh)

    resolver = OpenAICodexCredentialResolver(
        OpenAICodexProviderConfig(),
        credential_store=store,
    )

    credentials = await resolver()

    assert credentials.access_token == "new-access"
    assert credentials.account_id == "new-account"
    assert store.get_oauth("openai-codex") == OAuthCredential(
        access="new-access",
        refresh="new-refresh",
        expires=9999999999999,
        account_id="new-account",
    )
