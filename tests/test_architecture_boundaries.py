import ast
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK_ROOT = PROJECT_ROOT / "src" / "telegram_framework"
FORBIDDEN_PRODUCT_IMPORT_PREFIXES = (
    "src.bot",
    "src.calendar_provider",
    "src.config",
    "src.gemini_provider",
    "src.memory",
    "src.message_store",
    "src.model_provider",
    "src.openai_auth",
    "src.openai_provider",
    "src.provider_factory",
    "src.providers.gemini",
    "src.providers.openai",
    "src.settings_loader",
    "src.settings_models",
)


def _module_name_from_path(path: Path) -> str:
    return ".".join(path.relative_to(PROJECT_ROOT).with_suffix("").parts)


def _resolve_imported_module(
    *,
    current_module: str,
    imported_module: Optional[str],
    level: int,
) -> str:
    if level <= 0:
        return imported_module or ""

    package_parts = current_module.split(".")[:-1]
    trim_count = level - 1
    if trim_count > len(package_parts):
        return imported_module or ""
    base_parts = package_parts[: len(package_parts) - trim_count]
    if imported_module:
        return ".".join(base_parts + imported_module.split("."))
    return ".".join(base_parts)


def _is_forbidden_product_import(module_name: str) -> bool:
    if not module_name:
        return False
    return any(
        module_name == prefix or module_name.startswith(prefix + ".")
        for prefix in FORBIDDEN_PRODUCT_IMPORT_PREFIXES
    )


def test_framework_modules_do_not_import_product_layer() -> None:
    violations = []
    framework_files = sorted(FRAMEWORK_ROOT.rglob("*.py"))

    for module_path in framework_files:
        source = module_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(module_path))
        module_name = _module_name_from_path(module_path)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for imported in node.names:
                    imported_name = imported.name
                    if _is_forbidden_product_import(imported_name):
                        violations.append(
                            f"{module_name}:{node.lineno} imports {imported_name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                imported_name = _resolve_imported_module(
                    current_module=module_name,
                    imported_module=node.module,
                    level=node.level,
                )
                if _is_forbidden_product_import(imported_name):
                    violations.append(
                        f"{module_name}:{node.lineno} imports {imported_name}"
                    )

    assert violations == []
