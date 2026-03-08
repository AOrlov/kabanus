"""Runtime settings compatibility facade.

Public API compatibility:
- Exposes `Settings`, `ModelSpec`, `get_settings(force=False)`.
- Supports legacy module-level attribute access via `__getattr__`.
"""

from src import settings_loader
from src.settings_models import LEGACY_ATTR_TO_SETTINGS_FIELD, ModelSpec, Settings

_reload_env = settings_loader.reload_env


def get_settings(force: bool = False) -> Settings:
    return settings_loader.get_settings(force=force, reload_env_func=_reload_env)


def reset_settings_cache() -> None:
    settings_loader.reset_settings_cache()


def __getattr__(name: str):
    field_name = LEGACY_ATTR_TO_SETTINGS_FIELD.get(name)
    if field_name is not None:
        return getattr(get_settings(), field_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
