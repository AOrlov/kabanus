import subprocess
import sys


def test_dead_code_audit_script_passes() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/dead_code_audit.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "Dead-code audit failed.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
