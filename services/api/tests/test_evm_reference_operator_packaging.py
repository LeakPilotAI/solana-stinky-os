from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[3]
API_PYPROJECT = REPO_ROOT / "services" / "api" / "pyproject.toml"
RUNBOOK = REPO_ROOT / "docs" / "EVM_REFERENCE_OPERATOR.md"


def test_operator_console_script_is_packaged() -> None:
    config = tomllib.loads(API_PYPROJECT.read_text(encoding="utf-8"))
    scripts = config["project"]["scripts"]

    assert scripts["genesis-evm-reference-observe"] == (
        "stinky_api.evm_reference_operator_cli:main"
    )

    executable = shutil.which("genesis-evm-reference-observe")
    assert executable is not None

    completed = subprocess.run(
        [executable, "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0
    assert "Explicit read-only reference DEX observation" in completed.stdout
    assert "--rpc-env" in completed.stdout
    assert "--input" in completed.stdout


def test_operator_runbook_preserves_explicit_read_only_contract() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")

    required = (
        "genesis-evm-reference-observe",
        "--rpc-env",
        "https://",
        '"read_only": true',
        '"execution_authorized": false',
        "does not start a daemon or polling loop",
        "Live trading remains locked",
        "exact historical `block_number`",
    )
    for phrase in required:
        assert phrase in text

    assert "private keys" in text
    assert "transaction payloads" in text
    assert "Duplicate or replayed block requests fail closed" in text
