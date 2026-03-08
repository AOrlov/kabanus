import importlib
import sys


def _load_main():
    sys.modules.pop("src.main", None)
    module = importlib.import_module("src.main")
    return importlib.reload(module)


def test_import_has_no_startup_side_effects(monkeypatch) -> None:
    from src import logging_utils
    from src.bot import app as bot_app

    calls = []
    monkeypatch.setattr(
        logging_utils,
        "configure_bootstrap",
        lambda *args, **kwargs: calls.append("bootstrap"),
    )
    monkeypatch.setattr(bot_app, "run", lambda *args, **kwargs: calls.append("run"))

    _load_main()

    assert calls == []


def test_run_delegates_to_bot_app_with_startup_logging(monkeypatch) -> None:
    main = _load_main()
    calls = []

    monkeypatch.setattr(
        main.logging_utils,
        "configure_bootstrap",
        lambda: calls.append("bootstrap"),
    )
    monkeypatch.setattr(main.bot_app, "run", lambda: calls.append("run"))

    main.run()

    assert calls == [
        "bootstrap",
        "run",
    ]


def test_run_does_not_call_build_runtime_directly(monkeypatch) -> None:
    main = _load_main()

    monkeypatch.setattr(main.logging_utils, "configure_bootstrap", lambda: None)

    def _forbidden_build_runtime(*_args, **_kwargs):
        raise AssertionError("main should not compose runtime directly")

    monkeypatch.setattr(main.bot_app, "build_runtime", _forbidden_build_runtime)
    monkeypatch.setattr(main.bot_app, "run", lambda: None)

    main.run()
