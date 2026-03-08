from datetime import date
from types import SimpleNamespace

from src import config
from src import retry_utils
from src.gemini_provider import GeminiProvider, _ModelUsage
from src.providers.contracts import ReactionSelectionRequest


def test_model_usage_exhausted_until_next_day() -> None:
    usage = _ModelUsage()
    spec = config.ModelSpec(name="gemini-test", rpm=None, rpd=None)
    today = date(2024, 1, 1)
    now = 0.0

    assert usage.can_use(spec, now, today)

    usage.mark_exhausted(today)
    assert not usage.can_use(spec, now, today)

    next_day = date(2024, 1, 2)
    assert usage.can_use(spec, now, next_day)


def test_choose_reaction_includes_recent_context(monkeypatch) -> None:
    provider = GeminiProvider()
    settings = SimpleNamespace(
        gemini_models=[config.ModelSpec(name="gemini-2.0-flash", rpm=None, rpd=None)],
        thinking_budget=1024,
    )
    captured = {}

    class _FakeModels:
        def generate_content(self, **kwargs):
            captured["contents"] = kwargs["contents"]
            return SimpleNamespace(text="😀")

    class _FakeClient:
        def __init__(self) -> None:
            self.models = _FakeModels()

    monkeypatch.setattr(provider, "_get_client", lambda: (_FakeClient(), settings))

    def _fake_prepare_config(*args, **kwargs):
        captured["thinking_budget"] = kwargs.get("thinking_budget")
        return None

    monkeypatch.setattr(provider, "_prepare_config", _fake_prepare_config)

    def _fake_retry_with_item(*, max_attempts, pick_item, run, on_error):
        spec = pick_item()
        return run(spec)

    monkeypatch.setattr(retry_utils, "retry_with_item", _fake_retry_with_item)

    reaction = provider.select_reaction(
        ReactionSelectionRequest(
            message="ship it",
            allowed_reactions=["😀", "😴"],
            context_text="Alice: deploy in 10 minutes",
        )
    )

    assert reaction == "😀"
    assert "Current message: ship it" in captured["contents"]
    assert "Recent context:" in captured["contents"]
    assert "Alice: deploy in 10 minutes" in captured["contents"]
    assert "Allowed reactions: 😀, 😴" in captured["contents"]
    assert captured["thinking_budget"] == 0
