import asyncio
import time
from datetime import datetime
from types import SimpleNamespace

import pytest

from src.bot.services.reaction_service import (
    REACTION_ALLOWED_LIST,
    ReactionService,
    ReactionState,
)


class _ReactionProvider:
    def __init__(self, reaction: str) -> None:
        self._reaction = reaction
        self.calls = []

    def select_reaction(self, request):
        self.calls.append(request)
        return self._reaction


class _FailingReactionProvider:
    def select_reaction(self, request):
        del request
        raise RuntimeError("reaction unavailable")


class _ReactionMessage:
    def __init__(self) -> None:
        self.applied = []

    async def set_reaction(self, reaction: str) -> None:
        self.applied.append(reaction)


def _settings(**overrides):
    base = {
        "reaction_enabled": True,
        "reaction_daily_budget": 10,
        "reaction_cooldown_secs": 0.0,
        "reaction_messages_threshold": 1,
        "reaction_context_turns": 8,
        "reaction_context_token_limit": 1200,
        "debug_mode": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _service(*, provider, settings):
    return ReactionService(
        state=ReactionState(day=datetime.now().date()),
        reaction_selection_provider=provider,
        settings_getter=lambda: settings,
        get_all_messages_fn=lambda _chat_id: [
            {"sender": "Alice", "text": "one"},
            {"sender": "Bob", "text": "two"},
        ],
        assemble_context_fn=lambda messages, token_limit=None: "\n".join(
            f"{msg['sender']}: {msg['text']}" for msg in messages
        ),
        storage_id_fn=lambda _update: "9",
        log_context_fn=lambda _update: {},
    )


def _update():
    return SimpleNamespace(
        message=_ReactionMessage(),
        effective_user=SimpleNamespace(id=7),
        effective_chat=SimpleNamespace(id=9, type="group"),
        update_id=1,
    )


@pytest.mark.parametrize(
    ("settings_overrides", "state", "expected_provider_calls", "expected_reactions"),
    [
        (
            {"reaction_enabled": False},
            {"count": 0, "messages_since": 0, "last_ts": 0.0},
            0,
            0,
        ),
        (
            {"reaction_daily_budget": 1},
            {"count": 1, "messages_since": 0, "last_ts": 0.0},
            0,
            0,
        ),
        (
            {"reaction_cooldown_secs": 60.0},
            {"count": 0, "messages_since": 0, "last_ts": "now"},
            0,
            0,
        ),
        (
            {"reaction_messages_threshold": 2},
            {"count": 0, "messages_since": 0, "last_ts": 0.0},
            0,
            0,
        ),
        ({}, {"count": 0, "messages_since": 0, "last_ts": 0.0}, 1, 1),
    ],
)
def test_maybe_react_gating(
    settings_overrides,
    state,
    expected_provider_calls,
    expected_reactions,
) -> None:
    provider = _ReactionProvider(REACTION_ALLOWED_LIST[0])
    service = _service(
        provider=provider,
        settings=_settings(**settings_overrides),
    )
    service.state.count = state["count"]
    service.state.messages_since_last_reaction = state["messages_since"]
    service.state.last_ts = (
        time.monotonic() if state["last_ts"] == "now" else float(state["last_ts"])
    )

    update = _update()
    asyncio.run(service.maybe_react(update, "latest"))

    assert len(provider.calls) == expected_provider_calls
    assert len(update.message.applied) == expected_reactions


def test_maybe_react_propagates_provider_errors() -> None:
    service = _service(
        provider=_FailingReactionProvider(),
        settings=_settings(),
    )

    with pytest.raises(RuntimeError, match="reaction unavailable"):
        asyncio.run(service.maybe_react(_update(), "latest"))


def test_maybe_react_ignores_enabled_reactions_when_provider_missing() -> None:
    settings = _settings(reaction_enabled=False)
    service = _service(
        provider=None,
        settings=settings,
    )
    update = _update()

    asyncio.run(service.maybe_react(update, "latest"))

    settings.reaction_enabled = True
    asyncio.run(service.maybe_react(update, "latest"))

    assert update.message.applied == []
