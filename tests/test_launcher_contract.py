"""Launcher reliability contracts. Does not start Windows services.

Gate 1 must remain $150,000 / $200,000 clamp. This file only reads source.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def test_start_cmd_uses_script_dir_not_cd():
    t = read("Start-Stinky-OS.cmd")
    assert "%~dp0" in t
    assert "ExecutionPolicy Bypass" in t
    assert "pause" in t.lower()
    assert "WindowsPowerShell\\v1.0\\powershell.exe" in t
    # pause is not gated only on failure
    assert re.search(r"if errorlevel 1 \(\s*echo.*\s*pause\s*\)\s*$", t, re.I | re.S) is None
    assert t.lower().rfind("pause") > t.lower().rfind("if not")


def test_start_cmd_stays_open_on_success_and_failure():
    t = read("Start-Stinky-OS.cmd")
    assert "GENESIS STARTUP FAILED" in t
    assert "Closing this window will NOT stop Genesis" in t or "does NOT stop" in t


def test_shortcut_installer_absolute_cmd_exe():
    t = read("install-desktop-shortcut.ps1")
    assert "System32\\cmd.exe" in t
    assert "/d /k" in t
    assert "WorkingDirectory = $root" in t
    assert "TargetPath = $cmdExe" in t
    assert "$env:CD" not in t
    assert "Genesis.lnk" in t
    assert "Stop Genesis.lnk" in t


def test_start_has_duplicate_protection_before_stop():
    t = read("start-stinky.ps1")
    already = t.find("ALREADY RUNNING")
    restart_stop = t.find("Restart requested")
    assert already != -1
    assert restart_stop != -1
    assert already < restart_stop
    assert "Test-CoreHealthy" in t
    assert "if ($Restart)" in t


def test_start_writes_startup_log_and_redacts_secrets():
    t = read("start-stinky.ps1")
    assert "startup.log" in t
    assert "Redact-Line" in t
    assert "API_KEY" in t and "TOKEN" in t and "PASSWORD" in t
    assert "150k" in t or "150_000" in t or "150000" in t


def test_start_detaches_via_cmd_start():
    t = read("start-stinky.ps1")
    assert "cmd START" in t or "/c start" in t
    assert "genesis-$Name" in t or "genesis-" in t
    assert "Explorer job" in t or "break away" in t.lower() or "breaks away" in t


def test_start_health_uses_http_not_only_process():
    t = read("start-stinky.ps1")
    assert "http://127.0.0.1:8010/health" in t
    assert "http://127.0.0.1:3000/operator" in t
    assert "Wait-Http" in t
    assert "LIVE MARKET DATA" in t
    assert "LIVE GATE-1 EVENT" in t
    assert "UNKNOWN" in t


def test_browser_only_after_frontend_ready():
    t = read("start-stinky.ps1")
    assert "frontend is actually ready" in t
    open_at = t.find('Start-Process "http://127.0.0.1:3000/operator"')
    wait_at = t.find("http://127.0.0.1:3000/operator")
    assert wait_at != -1 and open_at != -1
    assert "browser launch failed - Genesis itself continues running" in t or "browser launch failed" in t


def test_stop_is_genesis_owned_only():
    t = read("stop-stinky.ps1")
    assert "Test-GenesisOwned" in t
    assert "Get-Process python" not in t
    assert "Get-Process node" not in t
    assert "Get-Process npm" not in t
    assert "taskkill /IM python" not in t.lower()
    assert "taskkill /IM node" not in t.lower()
    # must not indiscriminately kill 8001 (ATLAS risk)
    assert "foreach ($port in 8002, 8010, 3000, 8001)" not in t
    assert "foreach ($port in 8002, 8010, 3000)" in t
    assert "not Genesis-owned" in t
    assert "docker compose" in t
    assert "Docker Desktop" in t


def test_gate1_unchanged_in_admission():
    t = read("packages/stinky-core/src/stinky_core/admission.py")
    assert "GATE1_VOLUME_5M_USD = 150_000.0" in t
    assert "GATE1_VOLUME_CALIBRATION_MAX_USD = 200_000.0" in t


def test_aliases_exist():
    assert (ROOT / "Start-Genesis.cmd").exists()
    assert (ROOT / "Stop-Genesis.cmd").exists()
    assert (ROOT / "Start-Stinky-OS.cmd").exists()
    assert (ROOT / "Stop-Stinky-OS.cmd").exists()


def test_git_sync_is_opt_in():
    t = read("start-stinky.ps1")
    assert "[switch]$Sync" in t
    assert "if (-not $Sync) { return }" in t
    # must not always stop then git reset on every double-click
    begin = t.find("if (-not $Restart -and (Test-CoreHealthy))")
    assert begin != -1
    stop_always = t.find('Write-Step "[0] Stop previous instance"')
    assert stop_always == -1


def test_start_does_not_sleep_then_exit():
    t = read("start-stinky.ps1").strip()
    assert not t.endswith("Start-Sleep 6")
    assert "exit 0" in t and "exit 1" in t


def test_redact_line_contract():
    t = read("start-stinky.ps1")
    assert "Redact-Line" in t
    assert "***" in t
