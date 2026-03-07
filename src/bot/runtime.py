from dataclasses import dataclass
import logging
from typing import Callable

from src import config
from src.model_provider import ModelProvider


@dataclass(frozen=True)
class BotRuntime:
    model_provider: ModelProvider
    logger: logging.Logger
    get_settings: Callable[..., config.Settings]
