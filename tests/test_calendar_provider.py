from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from src import calendar_provider


class _FakeInsert:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def execute(self):
        return self._payload


class _FakeEventsApi:
    def __init__(self) -> None:
        self.last_calendar_id = None
        self.last_body = None

    def insert(self, calendarId, body):  # pylint: disable=invalid-name
        self.last_calendar_id = calendarId
        self.last_body = body
        return _FakeInsert(body)


class _FakeService:
    def __init__(self) -> None:
        self._events = _FakeEventsApi()

    def events(self):
        return self._events


def _provider_without_auth() -> calendar_provider.CalendarProvider:
    provider = calendar_provider.CalendarProvider.__new__(
        calendar_provider.CalendarProvider
    )
    provider.service = _FakeService()
    return provider


def test_create_event_all_day_uses_exclusive_end_date(monkeypatch) -> None:
    monkeypatch.setattr(
        calendar_provider.config,
        "get_settings",
        lambda: SimpleNamespace(google_calendar_id="calendar-1"),
    )
    provider = _provider_without_auth()

    result = provider.create_event(
        title="Offsite",
        is_all_day=True,
        start_time=date(2026, 1, 10),
    )

    assert result["start"]["date"] == "2026-01-10"
    assert result["end"]["date"] == "2026-01-11"
    assert provider.service.events().last_calendar_id == "calendar-1"


def test_create_event_timed_uses_local_timezone_without_utc_shift(monkeypatch) -> None:
    local_tz = timezone(timedelta(hours=3))
    monkeypatch.setattr(calendar_provider.tzlocal, "get_localzone", lambda: local_tz)
    monkeypatch.setattr(
        calendar_provider.config,
        "get_settings",
        lambda: SimpleNamespace(google_calendar_id="calendar-2"),
    )
    provider = _provider_without_auth()

    result = provider.create_event(
        title="Standup",
        is_all_day=False,
        start_time=datetime(2026, 1, 10, 9, 30),
    )

    assert result["start"]["dateTime"].startswith("2026-01-10T09:30:00+03:00")
    assert result["end"]["dateTime"].startswith("2026-01-10T10:30:00+03:00")
    assert result["start"]["timeZone"] == "UTC+03:00"
