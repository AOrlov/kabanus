import logging
import os
import tempfile
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

import tzlocal
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from src.bot.contracts import (
    CalendarProviderFactory,
    IsAllowedFn,
    LogContextFn,
    ProviderGetter,
    SettingsGetter,
)
from src.bot.services.media_service import IMAGE_MAX_BYTES


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class EventsHandler:
    def __init__(
        self,
        *,
        is_allowed_fn: IsAllowedFn,
        provider_getter: ProviderGetter,
        notify_admin_fn: Callable[[ContextTypes.DEFAULT_TYPE, str], Awaitable[None]],
        log_context_fn: LogContextFn,
        settings_getter: SettingsGetter,
        calendar_provider_factory: CalendarProviderFactory,
        logger_override: Optional[logging.Logger] = None,
    ) -> None:
        self._is_allowed = is_allowed_fn
        self._provider_getter = provider_getter
        self._notify_admin = notify_admin_fn
        self._log_context = log_context_fn
        self._settings_getter = settings_getter
        self._calendar_provider_factory = calendar_provider_factory
        self._logger = logger_override or logging.getLogger(__name__)

    async def schedule_events(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        settings = self._settings_getter()
        if not self._is_allowed(update) or not settings.features["schedule_events"]:
            return

        if (
            update.message is None
            or update.effective_chat is None
            or update.effective_user is None
        ):
            return

        if not update.message.photo:
            return

        await update.effective_chat.send_action(action=ChatAction.TYPING)

        temp_photo_path: Optional[str] = None
        try:
            photo = update.message.photo[-1]
            photo_size = _safe_int(getattr(photo, "file_size", None))
            if photo_size is not None and photo_size > IMAGE_MAX_BYTES:
                self._logger.warning(
                    "Photo too large for event scheduling",
                    extra={**self._log_context(update), "file_size": photo_size},
                )
                await update.message.reply_text(
                    "Sorry, this photo is too large to process."
                )
                return
            file = await context.bot.get_file(photo.file_id)
            resolved_file_size = _safe_int(getattr(file, "file_size", None))
            if resolved_file_size is None:
                resolved_file_size = photo_size
            if resolved_file_size is not None and resolved_file_size > IMAGE_MAX_BYTES:
                self._logger.warning(
                    "Photo too large for event scheduling",
                    extra={
                        **self._log_context(update),
                        "file_size": resolved_file_size,
                    },
                )
                await update.message.reply_text(
                    "Sorry, this photo is too large to process."
                )
                return

            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_photo:
                temp_photo_path = temp_photo.name
            await file.download_to_drive(temp_photo_path)
            try:
                downloaded_file_size = _safe_int(os.path.getsize(temp_photo_path))
            except OSError:
                downloaded_file_size = None
            if (
                downloaded_file_size is not None
                and downloaded_file_size > IMAGE_MAX_BYTES
            ):
                self._logger.warning(
                    "Photo too large for event scheduling",
                    extra={
                        **self._log_context(update),
                        "file_size": downloaded_file_size,
                    },
                )
                await update.message.reply_text(
                    "Sorry, this photo is too large to process."
                )
                return

            try:
                provider = self._provider_getter()
                event_data = provider.parse_image_to_event(temp_photo_path)

                confidence = _safe_float(event_data.get("confidence", 0))
                if confidence < 0.5:
                    await update.message.reply_text(
                        "I'm not very confident about the event details, but I'll create it anyway."
                    )

                calendar = self._calendar_provider_factory()

                if not event_data.get("date"):
                    raise ValueError("No date found in the event data")

                event_time = event_data.get("time")
                is_all_day = event_time is None
                if event_time is None:
                    self._logger.warning(
                        "No time found in event data, treating as all-day event",
                        extra=self._log_context(update),
                    )
                    event_time = "00:00"
                elif not isinstance(event_time, str):
                    self._logger.warning(
                        "Invalid time format, using default time of 00:00",
                        extra={**self._log_context(update), "event_time": event_time},
                    )
                    event_time = "00:00"

                try:
                    naive_datetime = datetime.strptime(
                        f"{event_data['date']} {event_time}",
                        "%Y-%m-%d %H:%M",
                    )
                except ValueError as exc:
                    self._logger.error(
                        "Failed to parse datetime",
                        extra={**self._log_context(update), "error": str(exc)},
                    )
                    raise ValueError(
                        f"Invalid date or time format: {event_data['date']} {event_time}"
                    )

                local_tz = tzlocal.get_localzone()
                start_time = naive_datetime.replace(tzinfo=local_tz)

                calendar.create_event(
                    title=event_data["title"],
                    is_all_day=is_all_day,
                    start_time=start_time,
                    location=event_data.get("location"),
                    description=event_data.get("description"),
                )

                formatted_time = start_time.strftime("%H:%M")
                message_parts = [
                    "Event created successfully!",
                    f"Title: {event_data['title']}",
                    f"Date: {event_data['date']}",
                    (
                        f"Time: {formatted_time} ({local_tz})"
                        if not is_all_day
                        else "All day event"
                    ),
                    f"Location: {event_data.get('location', 'Not specified')}",
                ]

                await update.message.reply_text("\n".join(message_parts))

            except Exception as exc:
                self._logger.error(
                    "Failed to process photo",
                    extra={**self._log_context(update), "error": str(exc)},
                )
                await update.message.reply_text(
                    "Sorry, I couldn't process the photo. Please make sure it contains clear event information."
                )
                await self._notify_admin(
                    context,
                    f"Photo processing failed for user {update.effective_user.id}: {exc}",
                )

        except Exception as exc:
            self._logger.error(
                "Failed to handle photo message",
                extra={**self._log_context(update), "error": str(exc)},
            )
            await update.message.reply_text(
                "Sorry, something went wrong while processing your photo."
            )
            await self._notify_admin(
                context,
                f"Photo message handling failed for user {update.effective_user.id}: {exc}",
            )
        finally:
            if temp_photo_path:
                try:
                    os.remove(temp_photo_path)
                except OSError:
                    self._logger.debug(
                        "Failed to remove temporary photo file",
                        extra={"path": temp_photo_path, **self._log_context(update)},
                    )
