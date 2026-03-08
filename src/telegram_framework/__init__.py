"""Reusable Telegram runtime framework primitives."""

from src.telegram_framework.application import build_application
from src.telegram_framework.error_reporting import (
    build_error_report_message,
    notify_admin,
    notify_admin_about_exception,
)
from src.telegram_framework.policy import is_allowed, log_context, storage_id
from src.telegram_framework.runtime import PollingRuntime, SettingsResolver

__all__ = [
    "PollingRuntime",
    "SettingsResolver",
    "build_application",
    "build_error_report_message",
    "is_allowed",
    "log_context",
    "notify_admin",
    "notify_admin_about_exception",
    "storage_id",
]
