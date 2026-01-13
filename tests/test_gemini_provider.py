from datetime import date

from src import config
from src.gemini_provider import _ModelUsage


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
