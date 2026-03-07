import os
import tempfile
from datetime import datetime
from typing import Any, Callable, Optional

import tzlocal
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from src.calendar_provider import CalendarProvider

from src.bot.access import is_allowed, log_context
from src.bot.runtime import BotRuntime


def _resolve_event_time(
    event_data: dict[str, Any],
    update: Update,
    runtime: BotRuntime,
) -> tuple[str, bool]:
    event_time = event_data.get("time")
    is_all_day = event_time is None
    if event_time is None:
        runtime.logger.warning(
            "No time found in event data, treating as all-day event",
            extra=log_context(update),
        )
        return "00:00", True
    if not isinstance(event_time, str):
        runtime.logger.warning(
            "Invalid time format, using default time of 00:00",
            extra={**log_context(update), "event_time": event_time},
        )
        return "00:00", is_all_day
    return event_time, is_all_day


def build_schedule_events_handler(
    runtime: BotRuntime,
    *,
    notify_admin: Callable[[ContextTypes.DEFAULT_TYPE, str], Any],
):
    async def schedule_events(  # pylint: disable=too-many-locals
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        settings = runtime.get_settings()
        if (
            not is_allowed(
                update,
                settings_getter=runtime.get_settings,
                logger=runtime.logger,
            )
            or not settings.features["schedule_events"]
        ):
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
            file = await context.bot.get_file(photo.file_id)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_photo:
                temp_photo_path = temp_photo.name
            await file.download_to_drive(temp_photo_path)

            try:
                event_data = runtime.model_provider.parse_image_to_event(
                    temp_photo_path
                )
                if event_data.get("confidence", 0) < 0.5:
                    await update.message.reply_text(
                        "I'm not very confident about the event details, but I'll create it anyway."
                    )

                calendar = CalendarProvider()
                if not event_data.get("date"):
                    raise ValueError("No date found in the event data")

                event_time, is_all_day = _resolve_event_time(
                    event_data, update, runtime
                )
                try:
                    naive_datetime = datetime.strptime(
                        f"{event_data['date']} {event_time}",
                        "%Y-%m-%d %H:%M",
                    )
                except ValueError as exc:
                    runtime.logger.error(
                        "Failed to parse datetime",
                        extra={**log_context(update), "error": str(exc)},
                    )
                    raise ValueError(
                        f"Invalid date or time format: {event_data['date']} {event_time}"
                    ) from exc

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
                        if event_data["time"]
                        else "All day event"
                    ),
                    f"Location: {event_data.get('location', 'Not specified')}",
                ]
                await update.message.reply_text("\n".join(message_parts))
            except Exception as exc:  # pylint: disable=broad-exception-caught
                runtime.logger.error(
                    "Failed to process photo",
                    extra={**log_context(update), "error": str(exc)},
                )
                await update.message.reply_text(
                    "Sorry, I couldn't process the photo. Please make sure it contains clear event information."
                )
                await notify_admin(
                    context,
                    f"Photo processing failed for user {update.effective_user.id}: {exc}",
                )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            runtime.logger.error(
                "Failed to handle photo message",
                extra={**log_context(update), "error": str(exc)},
            )
            await update.message.reply_text(
                "Sorry, something went wrong while processing your photo."
            )
            await notify_admin(
                context,
                f"Photo message handling failed for user {update.effective_user.id}: {exc}",
            )
        finally:
            if temp_photo_path:
                try:
                    os.remove(temp_photo_path)
                except OSError:
                    runtime.logger.debug(
                        "Failed to remove temporary photo file",
                        extra={"path": temp_photo_path, **log_context(update)},
                    )

    return schedule_events
