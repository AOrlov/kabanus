import importlib
import sys
from types import SimpleNamespace


def _load_main():
    sys.modules.pop("src.main", None)
    module = importlib.import_module("src.main")
    return importlib.reload(module)


def test_import_has_no_startup_side_effects(monkeypatch) -> None:
    from src import config, logging_utils
    from src.bot import app as bot_app

    calls = []
    monkeypatch.setattr(
        config, "get_settings", lambda *args, **kwargs: calls.append("settings")
    )
    monkeypatch.setattr(
        logging_utils,
        "configure_bootstrap",
        lambda *args, **kwargs: calls.append("bootstrap"),
    )
    monkeypatch.setattr(
        logging_utils,
        "configure_logging",
        lambda *args, **kwargs: calls.append("logging"),
    )
    monkeypatch.setattr(
        bot_app, "run_polling", lambda *args, **kwargs: calls.append("run_polling")
    )

    _load_main()

    assert calls == []


def test_run_delegates_to_bot_app_with_startup_logging(monkeypatch) -> None:
    main = _load_main()
    settings = SimpleNamespace(debug_mode=False)
    calls = []

    monkeypatch.setattr(
        main.logging_utils,
        "configure_bootstrap",
        lambda: calls.append("bootstrap"),
    )
    monkeypatch.setattr(
        main.config,
        "get_settings",
        lambda: (calls.append("settings"), settings)[1],
    )
    monkeypatch.setattr(
        main.logging_utils,
        "configure_logging",
        lambda configured: calls.append(("logging", configured)),
    )
    monkeypatch.setattr(
        main.bot_app, "run_polling", lambda: calls.append("run_polling")
    )

    main.run()

    assert calls == [
        "bootstrap",
        "settings",
        ("logging", settings),
        "run_polling",
    ]


def test_run_does_not_call_build_runtime_directly(monkeypatch) -> None:
    main = _load_main()

    monkeypatch.setattr(main.logging_utils, "configure_bootstrap", lambda: None)
    monkeypatch.setattr(
        main.config,
        "get_settings",
        lambda: SimpleNamespace(debug_mode=False),
    )
    monkeypatch.setattr(main.logging_utils, "configure_logging", lambda _settings: None)

    def _forbidden_build_runtime(*_args, **_kwargs):
        raise AssertionError("main should not compose runtime directly")

    monkeypatch.setattr(main.bot_app, "build_runtime", _forbidden_build_runtime)
    monkeypatch.setattr(main.bot_app, "run_polling", lambda: None)

    main.run()
