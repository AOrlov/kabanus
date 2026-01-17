import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict

_RESERVED_LOG_RECORD_ATTRS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "process",
    "processName",
}


def _coerce_json_value(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _extract_extra(record: logging.LogRecord) -> Dict[str, Any]:
    extras: Dict[str, Any] = {}
    for key, value in record.__dict__.items():
        if key in _RESERVED_LOG_RECORD_ATTRS or key.startswith("_"):
            continue
        extras[key] = _coerce_json_value(value)
    return extras


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        payload.update(_extract_extra(record))
        return json.dumps(payload, ensure_ascii=False)


def _configure_logging(level: int, log_format: str) -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
    handler.setLevel(level)
    root_logger.addHandler(handler)


def configure_bootstrap() -> None:
    log_format = os.getenv("LOG_FORMAT", "json").lower()
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    _configure_logging(level, log_format)


def configure_logging(settings) -> None:
    level = logging.DEBUG if settings.debug_mode else logging.INFO
    log_format = os.getenv("LOG_FORMAT", "json").lower()
    _configure_logging(level, log_format)


def update_log_level(level: int) -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for handler in root_logger.handlers:
        handler.setLevel(level)
