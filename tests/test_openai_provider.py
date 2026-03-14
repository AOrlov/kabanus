import base64
import json
from types import SimpleNamespace

import pytest

from src.providers.capabilities import AudioTranscriptionProvider
from src.providers.contracts import (
    ImageToEventRequest,
    ReactionSelectionRequest,
    TextGenerationRequest,
)
from src.providers.errors import ProviderConfigurationError
from src.providers.openai import OpenAIClientFactory, OpenAIProvider


def _settings(**openai_overrides):
    openai_settings = SimpleNamespace(
        api_key="openai-key",
        auth_json_path="",
        refresh_url="https://auth.openai.com/oauth/token",
        refresh_client_id="client-id",
        refresh_grant_type="refresh_token",
        auth_leeway_secs=60,
        auth_timeout_secs=20.0,
        codex_base_url="https://chatgpt.com/backend-api",
        codex_default_model="gpt-5.3-codex",
        text_model="gpt-5.3-codex",
        low_cost_model="gpt-5.3-codex",
        reaction_model="gpt-5.3-codex",
    )
    for key, value in openai_overrides.items():
        setattr(openai_settings, key, value)
    return SimpleNamespace(
        ai=SimpleNamespace(openai=openai_settings),
        language="ru",
    )


def _client_options(*, codex_mode: bool = False, refreshable: bool = False):
    return SimpleNamespace(codex_mode=codex_mode, refreshable=refreshable)


class _AuthManagerStub:
    def __init__(self, *, refreshable: bool) -> None:
        self._refreshable = refreshable

    def has_refresh_token(self) -> bool:
        return self._refreshable


def _jwt_with_account_id(account_id: str) -> str:
    def _b64(value: dict) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    header = _b64({"alg": "none"})
    payload = _b64({"https://api.openai.com/auth": {"chatgpt_account_id": account_id}})
    return f"{header}.{payload}.sig"


def test_resolve_client_options_uses_codex_backend_for_auth_json(monkeypatch) -> None:
    factory = OpenAIClientFactory(
        _settings(auth_json_path="auth.json").ai.openai,
        auth_manager=_AuthManagerStub(refreshable=True),
    )
    token = _jwt_with_account_id("acct_123")
    monkeypatch.setattr(factory, "_resolve_api_key", lambda force_refresh=False: token)

    options = factory.resolve_client_options()

    assert options.api_key == token
    assert options.base_url == "https://chatgpt.com/backend-api/codex"
    assert options.default_headers["chatgpt-account-id"] == "acct_123"
    assert options.default_headers["OpenAI-Beta"] == "responses=experimental"
    assert options.default_headers["originator"] == "pi"
    assert options.codex_mode is True
    assert options.refreshable is True


def test_resolve_client_options_rejects_refreshable_auth_without_account_id(
    monkeypatch,
) -> None:
    factory = OpenAIClientFactory(
        _settings(auth_json_path="auth.json").ai.openai,
        auth_manager=_AuthManagerStub(refreshable=True),
    )
    monkeypatch.setattr(
        factory, "_resolve_api_key", lambda force_refresh=False: "plain-token"
    )

    with pytest.raises(
        ProviderConfigurationError,
        match="chatgpt_account_id",
    ):
        factory.resolve_client_options()


def test_resolve_client_options_treats_api_key_file_as_standard_api_mode(
    monkeypatch,
) -> None:
    factory = OpenAIClientFactory(
        _settings(auth_json_path="auth.json").ai.openai,
        auth_manager=_AuthManagerStub(refreshable=False),
    )
    monkeypatch.setattr(
        factory,
        "_resolve_api_key",
        lambda force_refresh=False: "sk-test-api-key",
    )

    options = factory.resolve_client_options()

    assert options.api_key == "sk-test-api-key"
    assert options.codex_mode is False
    assert options.refreshable is False


class _FakeResponses:
    def __init__(self) -> None:
        self.calls = []

    class _StreamManager:
        def __init__(self, outer, kwargs):
            self._outer = outer
            self._kwargs = kwargs

        def __enter__(self):
            self._outer.calls.append(self._kwargs)
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def until_done(self):
            return self

        def get_final_response(self):
            return SimpleNamespace(output_text="ok")

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text="ok")

    def stream(self, **kwargs):
        return self._StreamManager(self, kwargs)


class _ModelFallbackResponses:
    def __init__(self) -> None:
        self.models = []

    class _StreamManager:
        def __init__(self, outer, kwargs):
            self._outer = outer
            self._kwargs = kwargs

        def __enter__(self):
            model = self._kwargs["model"]
            self._outer.models.append(model)
            if model == "legacy-unsupported-model":
                raise RuntimeError(
                    "The 'legacy-unsupported-model' model is not supported when using Codex with a ChatGPT account."
                )
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def until_done(self):
            return self

        def get_final_response(self):
            return SimpleNamespace(output_text="ok")

    def create(self, **kwargs):
        model = kwargs["model"]
        self.models.append(model)
        if model == "legacy-unsupported-model":
            raise RuntimeError(
                "The 'legacy-unsupported-model' model is not supported when using Codex with a ChatGPT account."
            )
        return SimpleNamespace(output_text="ok")

    def stream(self, **kwargs):
        return self._StreamManager(self, kwargs)


class _StreamingResponses:
    def __init__(self, deltas) -> None:
        self.calls = []
        self._deltas = list(deltas)

    class _StreamManager:
        def __init__(self, outer, kwargs):
            self._outer = outer
            self._kwargs = kwargs

        def __enter__(self):
            self._outer.calls.append(self._kwargs)
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            for delta in self._outer._deltas:
                yield SimpleNamespace(type="response.output_text.delta", delta=delta)

        def get_final_response(self):
            return SimpleNamespace(output_text="".join(self._outer._deltas))

    def stream(self, **kwargs):
        return self._StreamManager(self, kwargs)


class _StreamingModelFallbackResponses:
    def __init__(self) -> None:
        self.models = []

    class _StreamManager:
        def __init__(self, outer, kwargs):
            self._outer = outer
            self._kwargs = kwargs
            self._model = kwargs["model"]

        def __enter__(self):
            self._outer.models.append(self._model)
            if self._model == "legacy-unsupported-model":
                raise RuntimeError(
                    "The 'legacy-unsupported-model' model is not supported when using Codex with a ChatGPT account."
                )
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            yield SimpleNamespace(type="response.output_text.delta", delta="ok")

        def get_final_response(self):
            return SimpleNamespace(output_text="ok")

    def stream(self, **kwargs):
        return self._StreamManager(self, kwargs)


class _AuthFailStreamingResponses:
    class _StreamManager:
        def __enter__(self):
            raise RuntimeError("401 unauthorized")

        def __exit__(self, exc_type, exc, tb):
            return False

    def stream(self, **kwargs):
        _ = kwargs
        return self._StreamManager()


def test_generate_text_sets_instructions_in_codex_mode() -> None:
    fake = _FakeResponses()
    provider = OpenAIProvider(
        _settings(auth_json_path="x"),
        client_factory=SimpleNamespace(
            get_client_context=lambda force_refresh=False: (
                SimpleNamespace(responses=fake),
                _client_options(codex_mode=True, refreshable=True),
            )
        ),
    )

    result = provider.generate_text(TextGenerationRequest(prompt="hi"))

    assert result == "ok"
    assert fake.calls
    assert fake.calls[0]["instructions"] == "You are a helpful assistant."
    assert fake.calls[0]["store"] is False
    assert fake.calls[0].get("stream") is None


def test_generate_text_retries_with_codex_default_model() -> None:
    fake = _ModelFallbackResponses()
    provider = OpenAIProvider(
        _settings(auth_json_path="x", text_model="legacy-unsupported-model"),
        client_factory=SimpleNamespace(
            get_client_context=lambda force_refresh=False: (
                SimpleNamespace(responses=fake),
                _client_options(codex_mode=True, refreshable=True),
            )
        ),
    )

    result = provider.generate_text(TextGenerationRequest(prompt="hi"))

    assert result == "ok"
    assert fake.models == ["legacy-unsupported-model", "gpt-5.3-codex"]


def test_generate_stream_yields_progressive_snapshots() -> None:
    fake = _StreamingResponses(["he", "llo"])
    provider = OpenAIProvider(
        _settings(auth_json_path="x"),
        client_factory=SimpleNamespace(
            get_client_context=lambda force_refresh=False: (
                SimpleNamespace(responses=fake),
                _client_options(codex_mode=True, refreshable=True),
            )
        ),
    )

    snapshots = list(provider.generate_text_stream(TextGenerationRequest(prompt="hi")))

    assert snapshots == ["he", "hello"]
    assert fake.calls
    assert fake.calls[0]["instructions"] == "You are a helpful assistant."
    assert fake.calls[0]["store"] is False


def test_generate_stream_retries_with_codex_default_model() -> None:
    fake = _StreamingModelFallbackResponses()
    provider = OpenAIProvider(
        _settings(auth_json_path="x", text_model="legacy-unsupported-model"),
        client_factory=SimpleNamespace(
            get_client_context=lambda force_refresh=False: (
                SimpleNamespace(responses=fake),
                _client_options(codex_mode=True, refreshable=True),
            )
        ),
    )

    snapshots = list(provider.generate_text_stream(TextGenerationRequest(prompt="hi")))

    assert snapshots == ["ok"]
    assert fake.models == ["legacy-unsupported-model", "gpt-5.3-codex"]


def test_generate_stream_refreshes_auth_once() -> None:
    failing_client = SimpleNamespace(responses=_AuthFailStreamingResponses())
    success_responses = _StreamingResponses(["ok"])
    success_client = SimpleNamespace(responses=success_responses)
    calls = []

    def _get_client_context(force_refresh=False):
        calls.append(force_refresh)
        if force_refresh:
            return success_client, _client_options(codex_mode=False, refreshable=True)
        return failing_client, _client_options(codex_mode=False, refreshable=True)

    provider = OpenAIProvider(
        _settings(auth_json_path="x"),
        client_factory=SimpleNamespace(get_client_context=_get_client_context),
    )

    snapshots = list(provider.generate_text_stream(TextGenerationRequest(prompt="hi")))

    assert snapshots == ["ok"]
    assert calls == [False, True]


def test_choose_reaction_includes_recent_context(monkeypatch) -> None:
    provider = OpenAIProvider(_settings())
    captured = {}

    def _fake_run_text_request(
        *, capability, model, user_content, system_instruction=""
    ):
        captured["capability"] = capability
        captured["model"] = model
        captured["prompt"] = user_content[0]["text"]
        captured["system_instruction"] = system_instruction
        return "😀"

    monkeypatch.setattr(provider, "_run_text_request", _fake_run_text_request)

    reaction = provider.select_reaction(
        ReactionSelectionRequest(
            message="ship it",
            allowed_reactions=["😀", "😴"],
            context_text="Alice: deploy in 10 minutes",
        )
    )

    assert reaction == "😀"
    assert captured["capability"] == "reaction_selection"
    assert captured["model"] == "gpt-5.3-codex"
    assert "Current message: ship it" in captured["prompt"]
    assert "Recent context:" in captured["prompt"]
    assert "Alice: deploy in 10 minutes" in captured["prompt"]
    assert "Allowed reactions: 😀, 😴" in captured["prompt"]
    assert (
        "Return exactly one emoji from the allowed list."
        in captured["system_instruction"]
    )


def test_parse_image_event_returns_empty_dict_on_invalid_json(
    monkeypatch, tmp_path
) -> None:
    image_file = tmp_path / "event.jpg"
    image_file.write_bytes(b"img")
    provider = OpenAIProvider(_settings())
    monkeypatch.setattr(
        provider,
        "_run_text_request",
        lambda **kwargs: "not-json",
    )

    event = provider.parse_image_event(ImageToEventRequest(image_path=str(image_file)))

    assert event == {}


def test_provider_does_not_expose_transcription_capability() -> None:
    provider = OpenAIProvider(_settings())
    assert not isinstance(provider, AudioTranscriptionProvider)
