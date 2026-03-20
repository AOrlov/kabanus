import os
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai import errors

from src import config
from src.providers.contracts import ReactionSelectionRequest, TextGenerationRequest
from src.providers.errors import (
    ProviderAuthError,
    ProviderConfigurationError,
    ProviderResponseError,
)
from src.providers.gemini import (
    GeminiClientFactory,
    GeminiModelSelector,
    GeminiProvider,
    ModelUsage,
    SystemInstructionLoader,
)
from src.providers.gemini.response_parser import parse_event_payload


def _settings(
    *,
    api_key: str = "gem-key",
    default_model: str = "gemini-2.0-pro",
    low_cost_model: str = "gemini-2.0-flash",
    reaction_model: str = "gemma-3-27b-it",
    model_specs=None,
    thinking_budget: int = 1024,
    use_google_search: bool = False,
    system_instructions_path: str = "",
):
    return SimpleNamespace(
        ai=SimpleNamespace(
            gemini=SimpleNamespace(
                api_key=api_key,
                default_model=default_model,
                low_cost_model=low_cost_model,
                reaction_model=reaction_model,
                model_specs=model_specs
                or [
                    config.ModelSpec(name="gemini-2.0-pro", rpm=None, rpd=None),
                    config.ModelSpec(name="gemini-2.0-flash", rpm=None, rpd=None),
                    config.ModelSpec(name="gemma-3-27b-it", rpm=None, rpd=None),
                ],
                thinking_budget=thinking_budget,
                use_google_search=use_google_search,
                system_instructions_path=system_instructions_path,
            )
        ),
        language="ru",
    )


class _FakeModels:
    def __init__(self, responses_by_model) -> None:
        self._responses_by_model = {
            model_name: list(responses)
            for model_name, responses in responses_by_model.items()
        }
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        model_name = kwargs["model"]
        responses = self._responses_by_model.get(model_name, [])
        if not responses:
            raise AssertionError(f"unexpected Gemini model call: {model_name}")
        next_response = responses.pop(0)
        if isinstance(next_response, Exception):
            raise next_response
        return next_response


class _FakeClient:
    def __init__(self, responses_by_model) -> None:
        self.models = _FakeModels(responses_by_model)


class _FakeClientFactory:
    def __init__(self, client) -> None:
        self._client = client

    def get_client(self):
        return self._client


class _StaticInstructionLoader:
    def __init__(self, text: str) -> None:
        self._text = text

    def load(self) -> str:
        return self._text


def test_model_usage_exhausted_until_next_day() -> None:
    usage = ModelUsage()
    spec = config.ModelSpec(name="gemini-test", rpm=None, rpd=None)
    today = date(2024, 1, 1)
    now = 0.0

    assert usage.can_use(spec, now, today)

    usage.mark_exhausted(today)
    assert not usage.can_use(spec, now, today)

    next_day = date(2024, 1, 2)
    assert usage.can_use(spec, now, next_day)


def test_model_selector_uses_explicit_model_roles() -> None:
    selector = GeminiModelSelector(
        model_specs=[
            config.ModelSpec(name="gemini-2.0-pro", rpm=None, rpd=None),
            config.ModelSpec(name="gemini-2.0-flash", rpm=None, rpd=None),
            config.ModelSpec(name="gemma-3-27b-it", rpm=None, rpd=None),
        ],
        default_model="gemini-2.0-pro",
        low_cost_model="gemini-2.0-flash",
        reaction_model="gemma-3-27b-it",
    )

    assert [spec.name for spec in selector.text_generation_specs()] == [
        "gemini-2.0-pro",
        "gemini-2.0-flash",
        "gemma-3-27b-it",
    ]
    assert [spec.name for spec in selector.low_cost_specs()] == [
        "gemini-2.0-flash",
        "gemini-2.0-pro",
        "gemma-3-27b-it",
    ]
    assert [spec.name for spec in selector.reaction_specs()] == [
        "gemma-3-27b-it",
        "gemini-2.0-pro",
        "gemini-2.0-flash",
    ]


def test_model_selector_rejects_unknown_role_model() -> None:
    selector = GeminiModelSelector(
        model_specs=[config.ModelSpec(name="gemini-2.0-pro", rpm=None, rpd=None)],
        default_model="gemini-2.0-pro",
        low_cost_model="gemini-2.0-flash",
        reaction_model="gemini-2.0-pro",
    )

    with pytest.raises(
        ProviderConfigurationError, match="not present in GEMINI_MODELS"
    ):
        selector.low_cost_specs()


def test_system_instruction_loader_reads_relative_file(tmp_path: Path) -> None:
    instructions_file = tmp_path / "instructions.txt"
    instructions_file.write_text("follow the checklist", encoding="utf-8")
    loader = SystemInstructionLoader("instructions.txt", base_dir=tmp_path)

    assert loader.load() == "follow the checklist"


def test_system_instruction_loader_rejects_missing_file(tmp_path: Path) -> None:
    loader = SystemInstructionLoader("missing.txt", base_dir=tmp_path)

    with pytest.raises(ProviderConfigurationError, match="must point to a file"):
        loader.load()


def test_provider_resolves_relative_system_instructions_from_working_directory(
    monkeypatch,
    tmp_path: Path,
) -> None:
    instructions_file = tmp_path / "instructions.txt"
    instructions_file.write_text("follow the checklist", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    client = _FakeClient({"gemini-2.0-pro": [SimpleNamespace(text="reply")]})
    provider = GeminiProvider(
        _settings(system_instructions_path="instructions.txt"),
        client_factory=_FakeClientFactory(client),
    )

    reply = provider.generate_text(TextGenerationRequest(prompt="hello"))

    assert reply == "reply"
    assert client.models.calls[0]["config"].system_instruction == "follow the checklist"


def test_parse_event_payload_raises_typed_error_for_invalid_json() -> None:
    response = SimpleNamespace(text="not-json")

    with pytest.raises(ProviderResponseError, match="invalid event payload"):
        parse_event_payload(response, model_name="gemini-2.0-pro")


def test_get_client_uses_explicit_api_key_without_env_mutation(monkeypatch) -> None:
    captured = {}
    monkeypatch.setenv("GOOGLE_API_KEY", "original-env-key")

    class _ClientStub:
        def __init__(self, *, api_key):
            captured["api_key"] = api_key

    factory = GeminiClientFactory(
        _settings(api_key="explicit-key").ai.gemini,
        client_cls=_ClientStub,
    )

    factory.get_client()

    assert captured["api_key"] == "explicit-key"
    assert os.environ["GOOGLE_API_KEY"] == "original-env-key"


def test_generate_low_cost_uses_configured_low_cost_model() -> None:
    settings = _settings(
        default_model="gemini-2.0-pro",
        low_cost_model="gemini-2.0-flash",
        reaction_model="gemma-3-27b-it",
    )
    client = _FakeClient(
        {
            "gemini-2.0-flash": [SimpleNamespace(text="cheap reply")],
        }
    )
    provider = GeminiProvider(
        settings,
        client_factory=_FakeClientFactory(client),
        instruction_loader=_StaticInstructionLoader("system prompt"),
    )

    reply = provider.generate_low_cost_text(TextGenerationRequest(prompt="Summarize"))

    assert reply == "cheap reply"
    assert client.models.calls[0]["model"] == "gemini-2.0-flash"


def test_generate_text_retries_next_model_after_quota_error() -> None:
    settings = _settings(
        default_model="gemini-2.0-pro",
        low_cost_model="gemini-2.0-flash",
        reaction_model="gemma-3-27b-it",
    )
    client = _FakeClient(
        {
            "gemini-2.0-pro": [
                errors.ClientError(
                    429,
                    {"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota"}},
                )
            ],
            "gemini-2.0-flash": [SimpleNamespace(text="fallback reply")],
        }
    )
    provider = GeminiProvider(
        settings,
        client_factory=_FakeClientFactory(client),
        instruction_loader=_StaticInstructionLoader(""),
    )

    reply = provider.generate_text(TextGenerationRequest(prompt="hello"))

    assert reply == "fallback reply"
    assert [call["model"] for call in client.models.calls] == [
        "gemini-2.0-pro",
        "gemini-2.0-flash",
    ]


def test_generate_text_raises_typed_error_for_empty_response() -> None:
    settings = _settings()
    client = _FakeClient(
        {
            "gemini-2.0-pro": [SimpleNamespace(text="   ", candidates=[])],
        }
    )
    provider = GeminiProvider(
        settings,
        client_factory=_FakeClientFactory(client),
        instruction_loader=_StaticInstructionLoader(""),
    )

    with pytest.raises(ProviderResponseError, match="empty response"):
        provider.generate_text(TextGenerationRequest(prompt="hello"))


def test_generate_text_maps_auth_error_to_typed_error() -> None:
    settings = _settings()
    client = _FakeClient(
        {
            "gemini-2.0-pro": [
                errors.ClientError(
                    401,
                    {
                        "error": {
                            "status": "UNAUTHENTICATED",
                            "message": "bad key",
                        }
                    },
                )
            ],
        }
    )
    provider = GeminiProvider(
        settings,
        client_factory=_FakeClientFactory(client),
        instruction_loader=_StaticInstructionLoader(""),
    )

    with pytest.raises(ProviderAuthError, match="bad key"):
        provider.generate_text(TextGenerationRequest(prompt="hello"))


def test_choose_reaction_includes_recent_context() -> None:
    settings = _settings(
        default_model="gemini-2.0-pro",
        low_cost_model="gemini-2.0-flash",
        reaction_model="gemma-3-27b-it",
    )
    client = _FakeClient(
        {
            "gemma-3-27b-it": [SimpleNamespace(text="😀")],
        }
    )
    provider = GeminiProvider(
        settings,
        client_factory=_FakeClientFactory(client),
        instruction_loader=_StaticInstructionLoader(""),
    )

    reaction = provider.select_reaction(
        ReactionSelectionRequest(
            message="ship it",
            allowed_reactions=["😀", "😴"],
            context_text="Alice: deploy in 10 minutes",
        )
    )

    assert reaction == "😀"
    assert client.models.calls[0]["model"] == "gemma-3-27b-it"
    assert "Current message: ship it" in client.models.calls[0]["contents"]
    assert "Recent context:" in client.models.calls[0]["contents"]
    assert "Alice: deploy in 10 minutes" in client.models.calls[0]["contents"]
    assert "Allowed reactions: 😀, 😴" in client.models.calls[0]["contents"]
    assert client.models.calls[0]["config"].thinking_config is None


def test_provider_refreshes_runtime_settings_from_callable(monkeypatch) -> None:
    current_settings = {"value": _settings(default_model="gemini-2.0-pro")}

    class _Factory:
        def __init__(self, settings) -> None:
            self._settings = settings

        def get_client(self):
            return SimpleNamespace(
                models=SimpleNamespace(
                    generate_content=lambda **kwargs: SimpleNamespace(
                        text=f"{self._settings.default_model}:{kwargs['model']}"
                    )
                )
            )

    monkeypatch.setattr(
        "src.providers.gemini.provider.GeminiClientFactory",
        _Factory,
    )
    provider = GeminiProvider(
        lambda: current_settings["value"],
        instruction_loader=_StaticInstructionLoader(""),
    )

    first = provider.generate_text(TextGenerationRequest(prompt="hello"))
    current_settings["value"] = _settings(default_model="gemini-2.0-flash")
    second = provider.generate_text(TextGenerationRequest(prompt="hello"))

    assert first == "gemini-2.0-pro:gemini-2.0-pro"
    assert second == "gemini-2.0-flash:gemini-2.0-flash"
