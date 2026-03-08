import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET_MODULES = (
    PROJECT_ROOT / "src" / "bot" / "handlers" / "message_handler.py",
    PROJECT_ROOT / "src" / "bot" / "handlers" / "summary_handler.py",
    PROJECT_ROOT / "src" / "bot" / "handlers" / "events_handler.py",
    PROJECT_ROOT / "src" / "bot" / "services" / "reply_service.py",
    PROJECT_ROOT / "src" / "bot" / "services" / "reaction_service.py",
    PROJECT_ROOT / "src" / "bot" / "services" / "media_service.py",
)
FORBIDDEN_IMPORT_PREFIXES = (
    "src.config",
    "src.model_provider",
    "src.calendar_provider",
)


def _is_forbidden(module_name: str) -> bool:
    return any(
        module_name == prefix or module_name.startswith(prefix + ".")
        for prefix in FORBIDDEN_IMPORT_PREFIXES
    )


def test_product_handlers_and_services_use_contracts_instead_of_concrete_modules() -> (
    None
):
    violations = []
    for module_path in TARGET_MODULES:
        source = module_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(module_path))
        module_label = module_path.relative_to(PROJECT_ROOT).as_posix()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for imported in node.names:
                    if _is_forbidden(imported.name):
                        violations.append(
                            f"{module_label}:{node.lineno} imports {imported.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                imported_name = node.module or ""
                if _is_forbidden(imported_name):
                    violations.append(
                        f"{module_label}:{node.lineno} imports {imported_name}"
                    )

    assert violations == []
