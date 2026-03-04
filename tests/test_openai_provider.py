import base64
import json
from types import SimpleNamespace

from src.openai_provider import OpenAIProvider


def _jwt_with_account_id(account_id: str) -> str:
    def _b64(value: dict) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    header = _b64({"alg": "none"})
    payload = _b64({"https://api.openai.com/auth": {"chatgpt_account_id": account_id}})
    return f"{header}.{payload}.sig"


def test_resolve_client_options_uses_codex_backend_for_auth_json(monkeypatch) -> None:
    provider = OpenAIProvider()
    token = _jwt_with_account_id("acct_123")
    monkeypatch.setattr(provider, "_resolve_api_key", lambda _settings, force_refresh=False: token)
    monkeypatch.setattr(provider, "_get_auth_manager", lambda _settings: object())
    settings = SimpleNamespace(openai_codex_base_url="https://chatgpt.com/backend-api")

    api_key, base_url, headers = provider._resolve_client_options(settings)

    assert api_key == token
    assert base_url == "https://chatgpt.com/backend-api/codex"
    assert headers["chatgpt-account-id"] == "acct_123"
    assert headers["OpenAI-Beta"] == "responses=experimental"
    assert headers["originator"] == "pi"


def test_resolve_client_options_falls_back_without_account_id(monkeypatch) -> None:
    provider = OpenAIProvider()
    monkeypatch.setattr(provider, "_resolve_api_key", lambda _settings, force_refresh=False: "plain-token")
    monkeypatch.setattr(provider, "_get_auth_manager", lambda _settings: object())
    settings = SimpleNamespace(openai_codex_base_url="https://chatgpt.com/backend-api")

    api_key, base_url, headers = provider._resolve_client_options(settings)

    assert api_key == "plain-token"
    assert base_url is None
    assert headers == {}


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


def test_responses_create_sets_instructions_in_codex_mode(monkeypatch) -> None:
    provider = OpenAIProvider()
    fake = _FakeResponses()
    client = SimpleNamespace(responses=fake)
    settings = SimpleNamespace(
        openai_auth_json_path="x",
        openai_codex_default_model="gpt-5.3-codex",
    )
    monkeypatch.setattr(provider, "_get_client", lambda force_refresh=False: (client, settings))

    result = provider._responses_create(
        model="gpt-5.3-codex",
        user_content=[{"type": "input_text", "text": "hi"}],
    )

    assert result == "ok"
    assert fake.calls
    assert fake.calls[0]["instructions"] == "You are a helpful assistant."
    assert fake.calls[0]["store"] is False
    assert fake.calls[0].get("stream") is None


def test_responses_create_retries_with_codex_default_model(monkeypatch) -> None:
    provider = OpenAIProvider()
    fake = _ModelFallbackResponses()
    client = SimpleNamespace(responses=fake)
    settings = SimpleNamespace(
        openai_auth_json_path="x",
        openai_codex_default_model="gpt-5.3-codex",
    )
    monkeypatch.setattr(provider, "_get_client", lambda force_refresh=False: (client, settings))

    result = provider._responses_create(
        model="legacy-unsupported-model",
        user_content=[{"type": "input_text", "text": "hi"}],
    )

    assert result == "ok"
    assert fake.models == ["legacy-unsupported-model", "gpt-5.3-codex"]


def test_choose_reaction_includes_recent_context(monkeypatch) -> None:
    provider = OpenAIProvider()
    settings = SimpleNamespace(openai_reaction_model="gpt-5.3-codex")
    monkeypatch.setattr(
        provider,
        "_get_client",
        lambda force_refresh=False: (SimpleNamespace(), settings),
    )
    captured = {}

    def _fake_responses_create(*, model, user_content, system_instruction=""):
        captured["model"] = model
        captured["prompt"] = user_content[0]["text"]
        return "😀"

    monkeypatch.setattr(provider, "_responses_create", _fake_responses_create)

    reaction = provider.choose_reaction(
        "ship it",
        ["😀", "😴"],
        context_text="Alice: deploy in 10 minutes",
    )

    assert reaction == "😀"
    assert captured["model"] == "gpt-5.3-codex"
    assert "Current message: ship it" in captured["prompt"]
    assert "Recent context:" in captured["prompt"]
    assert "Alice: deploy in 10 minutes" in captured["prompt"]
    assert "Allowed reactions: 😀, 😴" in captured["prompt"]
