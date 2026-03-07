import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional, Union

import tzlocal
from google.oauth2 import service_account
from googleapiclient.discovery import build  # type: ignore[import-untyped]

from src import config

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
logger = logging.getLogger(__name__)


class CalendarProvider:
    def __init__(self) -> None:
        self.service = None
        self._authenticate()

    def _authenticate(self) -> None:
        settings = config.get_settings()
        try:
            if settings.google_credentials_path:
                credentials = service_account.Credentials.from_service_account_file(
                    settings.google_credentials_path,
                    scopes=SCOPES,
                )
            elif settings.google_credentials_json:
                credentials_info = json.loads(settings.google_credentials_json)
                credentials = service_account.Credentials.from_service_account_info(
                    credentials_info,
                    scopes=SCOPES,
                )
            else:
                raise RuntimeError("Missing Google Calendar credentials.")
            self.service = build("calendar", "v3", credentials=credentials)
        except json.JSONDecodeError as exc:
            raise RuntimeError("GOOGLE_CREDENTIALS_JSON is not valid JSON.") from exc
        except Exception as exc:
            raise RuntimeError(
                f"Failed to authenticate with Google Calendar: {exc}"
            ) from exc

    def _all_day_bounds(self, start_time: Union[datetime, date]) -> tuple[date, date]:
        start_date = (
            start_time.date() if isinstance(start_time, datetime) else start_time
        )
        # Google Calendar requires an exclusive end date for all-day events.
        end_date = start_date + timedelta(days=1)
        return start_date, end_date

    def _ensure_timezone(self, value: datetime) -> datetime:
        if value.tzinfo is not None:
            return value
        return value.replace(tzinfo=tzlocal.get_localzone())

    def create_event(
        self,
        title: str,
        is_all_day: bool,
        start_time: Union[datetime, date],
        end_time: Optional[datetime] = None,
        location: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        if self.service is None:
            raise RuntimeError("Calendar service is not initialized")

        settings = config.get_settings()
        if not settings.google_calendar_id:
            raise RuntimeError("GOOGLE_CALENDAR_ID is required to create events")

        event: Dict[str, Any] = {"summary": title}
        if is_all_day:
            start_date, final_date = self._all_day_bounds(start_time)
            event["start"] = {"date": start_date.isoformat()}
            event["end"] = {"date": final_date.isoformat()}
        else:
            if not isinstance(start_time, datetime):
                raise ValueError("start_time must be datetime for non all-day events")
            start_dt = self._ensure_timezone(start_time)
            end_dt = self._ensure_timezone(end_time or (start_dt + timedelta(hours=1)))
            tz_name = str(start_dt.tzinfo or tzlocal.get_localzone())
            event["start"] = {"dateTime": start_dt.isoformat(), "timeZone": tz_name}
            event["end"] = {"dateTime": end_dt.isoformat(), "timeZone": tz_name}

        if location:
            event["location"] = location
        if description:
            event["description"] = description

        logger.debug(
            "Creating Google Calendar event",
            extra={"calendar_id": settings.google_calendar_id, "event": event},
        )

        try:
            return (
                self.service.events()
                .insert(
                    calendarId=settings.google_calendar_id,
                    body=event,
                )
                .execute()
            )
        except Exception as exc:
            error_msg = f"Failed to create calendar event: {exc}"
            if hasattr(exc, "content"):
                error_msg += f"\nError details: {getattr(exc, 'content')}"
            raise RuntimeError(error_msg) from exc
