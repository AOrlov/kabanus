import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Optional

from telegram import Update
from telegram.constants import ReactionEmoji

from src.bot.contracts import (
    AssembleContextFn,
    BotSettings,
    GetAllMessagesFn,
    LogContextFn,
    ProviderGetter,
    StorageIdFn,
)
from src.providers.contracts import ReactionSelectionRequest

REACTION_ALLOWED_SET = {emoji.value for emoji in ReactionEmoji}
REACTION_ALLOWED_LIST = sorted(REACTION_ALLOWED_SET)


@dataclass
class ReactionState:
    day: Optional[date] = None
    count: int = 0
    last_ts: float = 0.0
    messages_since_last_reaction: int = 0


class ReactionService:
    def __init__(
        self,
        *,
        state: ReactionState,
        provider_getter: ProviderGetter,
        settings_getter: Callable[[], BotSettings],
        get_all_messages_fn: GetAllMessagesFn,
        assemble_context_fn: AssembleContextFn,
        storage_id_fn: StorageIdFn,
        allowed_reactions: Optional[list[str]] = None,
        allowed_reaction_set: Optional[set[str]] = None,
        log_context_fn: LogContextFn,
        logger_override: Optional[logging.Logger] = None,
    ) -> None:
        self._state = state
        self._provider_getter = provider_getter
        self._settings_getter = settings_getter
        self._get_all_messages = get_all_messages_fn
        self._assemble_context = assemble_context_fn
        self._storage_id = storage_id_fn
        self._allowed_reactions = list(allowed_reactions or REACTION_ALLOWED_LIST)
        self._allowed_reaction_set = set(allowed_reaction_set or REACTION_ALLOWED_SET)
        self._log_context = log_context_fn
        self._logger = logger_override or logging.getLogger(__name__)
        self._state_lock = asyncio.Lock()

    @property
    def state(self) -> ReactionState:
        return self._state

    def _reset_reaction_budget_if_needed(self, now: datetime) -> None:
        today = now.date()
        if self._state.day != today:
            self._state.day = today
            self._state.count = 0

    def _build_reaction_context(
        self, chat_id: Optional[str], settings: BotSettings
    ) -> str:
        if (
            not chat_id
            or settings.reaction_context_turns <= 0
            or settings.reaction_context_token_limit <= 0
        ):
            return ""

        messages = self._get_all_messages(chat_id)
        if not messages:
            return ""

        recent_messages = messages[-settings.reaction_context_turns :]
        return self._assemble_context(
            recent_messages,
            token_limit=settings.reaction_context_token_limit,
        )

    async def maybe_react(self, update: Update, text: str) -> None:
        self._logger.debug("maybe_react called", extra=self._log_context(update))
        async with self._state_lock:
            settings = self._settings_getter()

            if update.message is None or not settings.reaction_enabled:
                return

            self._state.messages_since_last_reaction += 1
            self._reset_reaction_budget_if_needed(datetime.now())

            if (
                settings.reaction_daily_budget <= 0
                or self._state.count >= settings.reaction_daily_budget
            ):
                return

            if settings.reaction_cooldown_secs > 0:
                if (
                    time.monotonic() - self._state.last_ts
                    < settings.reaction_cooldown_secs
                ):
                    return

            if (
                self._state.messages_since_last_reaction
                < settings.reaction_messages_threshold
            ):
                return

            chat_storage_id = self._storage_id(update)
            reaction_context = self._build_reaction_context(chat_storage_id, settings)
            if settings.debug_mode:
                self._logger.debug(
                    "Built reaction context",
                    extra={
                        **self._log_context(update),
                        "has_context": bool(reaction_context),
                        "context_chars": len(reaction_context),
                        "context_preview": reaction_context[:256],
                    },
                )

            provider = self._provider_getter()
            reaction = provider.select_reaction(
                ReactionSelectionRequest(
                    message=text,
                    allowed_reactions=self._allowed_reactions,
                    context_text=reaction_context,
                )
            ).strip()
            if not reaction:
                return

            if reaction not in self._allowed_reaction_set:
                self._logger.warning(
                    "Model returned unsupported reaction: %s", reaction
                )
                return

            try:
                await update.message.set_reaction(reaction)
            except Exception as exc:
                self._logger.warning("Failed to set reaction: %s", exc)
                return

            self._state.count += 1
            self._state.last_ts = time.monotonic()
            self._state.messages_since_last_reaction = 0
