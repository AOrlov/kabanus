from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
)

from src.providers.contracts import CapabilityName
from telegram import Update
from src.providers.capabilities import (
    AudioTranscriptionProvider,
    EventParsingProvider,
    LowCostTextGenerationProvider,
    OcrProvider,
    ReactionSelectionProvider,
    StreamingTextGenerationProvider,
    TextGenerationProvider,
)


class BotSettings(Protocol):
    @property
    def features(self) -> Mapping[str, Any]: ...

    @property
    def bot_aliases(self) -> Sequence[str]: ...

    @property
    def debug_mode(self) -> bool: ...

    @property
    def telegram_format_ai_replies(self) -> bool: ...

    @property
    def telegram_use_message_drafts(self) -> bool: ...

    @property
    def telegram_bot_token(self) -> str: ...

    @property
    def telegram_draft_update_interval_secs(self) -> float: ...

    @property
    def reaction_enabled(self) -> bool: ...

    @property
    def reaction_cooldown_secs(self) -> float: ...

    @property
    def reaction_daily_budget(self) -> int: ...

    @property
    def reaction_messages_threshold(self) -> int: ...

    @property
    def reaction_context_turns(self) -> int: ...

    @property
    def reaction_context_token_limit(self) -> int: ...


@dataclass(frozen=True)
class MessageFlowCapabilities:
    text_generation: Optional[TextGenerationProvider] = None
    streaming_text_generation: Optional[StreamingTextGenerationProvider] = None
    low_cost_text_generation: Optional[LowCostTextGenerationProvider] = None
    audio_transcription: Optional[AudioTranscriptionProvider] = None
    ocr: Optional[OcrProvider] = None
    reaction_selection: Optional[ReactionSelectionProvider] = None


@dataclass(frozen=True)
class EventsCapabilities:
    event_parsing: Optional[EventParsingProvider] = None


@dataclass(frozen=True)
class RuntimeCapabilities:
    message_flow: MessageFlowCapabilities = field(
        default_factory=MessageFlowCapabilities
    )
    events: EventsCapabilities = field(default_factory=EventsCapabilities)


def compose_runtime_capabilities(provider: object) -> RuntimeCapabilities:
    return RuntimeCapabilities(
        message_flow=MessageFlowCapabilities(
            text_generation=(
                provider if isinstance(provider, TextGenerationProvider) else None
            ),
            streaming_text_generation=(
                provider
                if isinstance(provider, StreamingTextGenerationProvider)
                else None
            ),
            low_cost_text_generation=(
                provider
                if isinstance(provider, LowCostTextGenerationProvider)
                else None
            ),
            audio_transcription=(
                provider if isinstance(provider, AudioTranscriptionProvider) else None
            ),
            ocr=provider if isinstance(provider, OcrProvider) else None,
            reaction_selection=(
                provider if isinstance(provider, ReactionSelectionProvider) else None
            ),
        ),
        events=EventsCapabilities(
            event_parsing=(
                provider if isinstance(provider, EventParsingProvider) else None
            )
        ),
    )


def available_runtime_capabilities(
    capabilities: RuntimeCapabilities,
) -> Sequence[CapabilityName]:
    available: List[CapabilityName] = []
    if capabilities.message_flow.text_generation is not None:
        available.append("text_generation")
    if capabilities.message_flow.streaming_text_generation is not None:
        available.append("streaming_text_generation")
    if capabilities.message_flow.low_cost_text_generation is not None:
        available.append("low_cost_text_generation")
    if capabilities.message_flow.audio_transcription is not None:
        available.append("audio_transcription")
    if capabilities.message_flow.ocr is not None:
        available.append("ocr")
    if capabilities.message_flow.reaction_selection is not None:
        available.append("reaction_selection")
    if capabilities.events.event_parsing is not None:
        available.append("event_parsing")
    return available


SettingsGetter = Callable[[], BotSettings]
IsAllowedFn = Callable[[Update], bool]
StorageIdFn = Callable[[Update], Optional[str]]
LogContextFn = Callable[[Optional[Update]], Mapping[str, Any]]
AddMessageFn = Callable[..., None]
GetAllMessagesFn = Callable[[str], Sequence[Mapping[str, Any]]]
GetMessageByTelegramMessageIdFn = Callable[[str, int], Optional[Mapping[str, Any]]]
BuildContextFn = Callable[..., str]
AssembleContextFn = Callable[..., str]
GetSummaryViewTextFn = Callable[..., str]


class CalendarProvider(Protocol):
    def create_event(self, *args: Any, **kwargs: Any) -> Any: ...


CalendarProviderFactory = Callable[[], CalendarProvider]
