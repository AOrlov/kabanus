"""Runtime settings compatibility facade.

Public API compatibility:
- Exposes `Settings`, `ModelSpec`, `get_settings(force=False)`.
"""

from src import settings_loader
from src.settings_models import ModelSpec, Settings

_reload_env = settings_loader.reload_env


def get_settings(force: bool = False) -> Settings:
    return settings_loader.get_settings(force=force, reload_env_func=_reload_env)


def reset_settings_cache() -> None:
    settings_loader.reset_settings_cache()
