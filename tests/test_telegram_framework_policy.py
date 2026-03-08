from types import SimpleNamespace

from src.telegram_framework import policy


class _Logger:
    def __init__(self) -> None:
        self.warning_calls = []
        self.info_calls = []

    def warning(self, message, *, extra):
        self.warning_calls.append((message, extra))

    def info(self, message, *, extra):
        self.info_calls.append((message, extra))


def _update(*, user_id=1, chat_id=2, chat_type="group", update_id=3):
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=chat_id, type=chat_type),
        update_id=update_id,
    )


def test_log_context_extracts_expected_ids() -> None:
    update = _update(user_id=11, chat_id=22, update_id=33)

    assert policy.log_context(update) == {
        "user_id": 11,
        "chat_id": 22,
        "update_id": 33,
    }


def test_storage_id_uses_user_id_for_private_chat() -> None:
    update = _update(user_id=11, chat_id=22, chat_type="private")

    assert policy.storage_id(update) == "11"


def test_storage_id_uses_chat_id_for_group_chat() -> None:
    update = _update(user_id=11, chat_id=22, chat_type="group")

    assert policy.storage_id(update) == "22"


def test_is_allowed_accepts_match_by_chat_or_user_id() -> None:
    logger = _Logger()
    update = _update(user_id=55, chat_id=77)

    allowed_by_chat = policy.is_allowed(
        update,
        settings_getter=lambda: SimpleNamespace(allowed_chat_ids=["77"]),
        logger_override=logger,
    )
    allowed_by_user = policy.is_allowed(
        update,
        settings_getter=lambda: SimpleNamespace(allowed_chat_ids=["55"]),
        logger_override=logger,
    )

    assert allowed_by_chat is True
    assert allowed_by_user is True


def test_is_allowed_rejects_unauthorized_and_logs_warning() -> None:
    logger = _Logger()
    update = _update(user_id=55, chat_id=77)

    result = policy.is_allowed(
        update,
        settings_getter=lambda: SimpleNamespace(allowed_chat_ids=["42"]),
        logger_override=logger,
    )

    assert result is False
    assert logger.warning_calls == [
        (
            "Unauthorized access attempt",
            {"user_id": "55", "chat_id": "77"},
        )
    ]


def test_is_allowed_rejects_when_allowlist_missing() -> None:
    logger = _Logger()
    update = _update(user_id=55, chat_id=77, update_id=88)

    result = policy.is_allowed(
        update,
        settings_getter=lambda: SimpleNamespace(allowed_chat_ids=[]),
        logger_override=logger,
    )

    assert result is False
    assert logger.info_calls == [
        (
            "No allowed_chat_ids configured, disallowing all users",
            {"user_id": 55, "chat_id": 77, "update_id": 88},
        )
    ]
