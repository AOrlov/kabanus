#!/usr/bin/env python3
"""Dead-code and module-boundary audit for runtime, memory, and provider layers."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    "src/bot",
    "src/memory",
    "src/model_provider.py",
    "src/provider_factory.py",
    "src/openai_provider.py",
    "src/gemini_provider.py",
    "src/openai_auth.py",
]

# Reviewed dead-code candidates from vulture for this scope.
REVIEWED_FINDINGS: Dict[str, str] = {
    "src/bot/app.py:refresh_settings_job": (
        "Runtime callback is referenced by scheduler wiring and runtime tests."
    ),
    "src/bot/contracts.py:description": (
        "Protocol parameter name used as part of calendar event contract."
    ),
    "src/bot/contracts.py:location": (
        "Protocol parameter name used as part of calendar event contract."
    ),
    "src/memory/history_store.py:clear_cache": (
        "Public cache-control API used by message_store and tests."
    ),
    "src/memory/history_store.py:get_last_message": (
        "Public history API used via message_store."
    ),
    "src/memory/summary_store.py:clear_cache": (
        "Public cache-control API used by message_store and tests."
    ),
    "src/memory/summary_store.py:load_summary_state": (
        "Public summary-state API used by tests and diagnostics."
    ),
    "src/memory/summary_store.py:save_summary_state": (
        "Public summary-state API used by tests and diagnostics."
    ),
}

# Symbols that were removed in Task 6 and must stay removed.
REMOVED_SYMBOLS: Set[str] = {
    "src/bot/services/reply_service.py:should_use_message_drafts",
}

_VULTURE_LINE_RE = re.compile(
    r"^(?P<path>[^:]+):\d+:\s+unused\s+(?:function|method|variable)\s+'(?P<name>[^']+)'"
)


def _iter_target_files() -> Iterable[Path]:
    for target in TARGETS:
        path = ROOT / target
        if path.is_file():
            yield path
            continue
        if path.is_dir():
            yield from sorted(path.rglob("*.py"))


def _run_vulture() -> List[str]:
    command = [sys.executable, "-m", "vulture", *TARGETS, "--min-confidence", "60"]
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 3):
        raise RuntimeError(
            "vulture failed unexpectedly\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _finding_key(vulture_line: str) -> str:
    match = _VULTURE_LINE_RE.match(vulture_line)
    if not match:
        raise ValueError(f"Unexpected vulture output line: {vulture_line}")
    return f"{match.group('path')}:{match.group('name')}"


def _find_private_cross_module_accesses() -> List[Tuple[str, int, str]]:
    violations: List[Tuple[str, int, str]] = []
    for path in _iter_target_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported_src_aliases: Dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("src."):
                        local_name = alias.asname or alias.name.split(".")[-1]
                        imported_src_aliases[local_name] = alias.name
            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                if module_name == "src" or module_name.startswith("src."):
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        local_name = alias.asname or alias.name
                        imported_src_aliases[local_name] = f"{module_name}.{alias.name}"

        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            if not node.attr.startswith("_"):
                continue
            if not isinstance(node.value, ast.Name):
                continue
            alias = node.value.id
            if alias not in imported_src_aliases:
                continue
            violations.append(
                (
                    path.relative_to(ROOT).as_posix(),
                    node.lineno,
                    f"{alias}.{node.attr}",
                )
            )
    return violations


def main() -> int:
    findings = sorted({_finding_key(line) for line in _run_vulture()})
    unexpected_findings = sorted(set(findings) - set(REVIEWED_FINDINGS))
    removed_symbol_regressions = sorted(set(findings) & REMOVED_SYMBOLS)
    boundary_violations = _find_private_cross_module_accesses()

    print("Reviewed dead-code candidates:")
    if findings:
        for key in findings:
            reason = REVIEWED_FINDINGS.get(key, "UNREVIEWED")
            print(f"- {key}: {reason}")
    else:
        print("- none")

    if boundary_violations:
        print("\nCross-module private access violations:")
        for file_path, line_no, symbol in boundary_violations:
            print(f"- {file_path}:{line_no}: {symbol}")

    if unexpected_findings:
        print("\nUnreviewed dead-code candidates:")
        for key in unexpected_findings:
            print(f"- {key}")

    if removed_symbol_regressions:
        print("\nRemoved symbols reintroduced:")
        for key in removed_symbol_regressions:
            print(f"- {key}")

    return (
        0
        if not unexpected_findings
        and not removed_symbol_regressions
        and not boundary_violations
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
