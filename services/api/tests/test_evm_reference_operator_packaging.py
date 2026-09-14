from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[3]
API_PYPROJECT = REPO_ROOT / "services" / "api" / "pyproject.toml"
RUNBOOK = REPO_ROOT / "docs" / "EVM_REFERENCE_OPERATOR.md"


def test_operator_console_scripts_are_packaged() -> None:
    config = tomllib.loads(API_PYPROJECT.read_text(encoding="utf-8"))
    scripts = config["project"]["scripts"]

    assert scripts["genesis-evm-reference-observe"] == (
        "stinky_api.evm_reference_operator_cli:main"
    )
    assert scripts["genesis-evm-reference-preflight"] == (
        "stinky_api.evm_reference_operator_preflight_cli:main"
    )

    observe = shutil.which("genesis-evm-reference-observe")
    preflight = shutil.which("genesis-evm-reference-preflight")
    assert observe is not None
    assert preflight is not None

    observe_help = subprocess.run(
        [observe, "--help"], check=False, capture_output=True, text=True, timeout=10
    )
    assert observe_help.returncode == 0
    assert "--rpc-env" in observe_help.stdout
    assert "--input" in observe_help.stdout

    preflight_help = subprocess.run(
        [preflight, "--help"], check=False, capture_output=True, text=True, timeout=10
    )
    assert preflight_help.returncode == 0
    assert "completely offline" in preflight_help.stdout
    assert "--input" in preflight_help.stdout
    assert "--rpc-env" not in preflight_help.stdout


def test_operator_runbook_preserves_explicit_read_only_contract() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")

    required = (
        "genesis-evm-reference-observe",
        "genesis-evm-reference-preflight",
        "--rpc-env",
        "https://",
        '"read_only": true',
        '"execution_authorized": false',
        "does not start a daemon or polling loop",
        "Live trading remains locked",
        "exact historical `block_number`",
        "completely offline",
    )
    for phrase in required:
        assert phrase in text

    assert "private keys" in text
    assert "transaction payloads" in text
    assert "Duplicate or replayed block requests fail closed" in text
