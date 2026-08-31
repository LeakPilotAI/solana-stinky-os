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
    assert "start_genesis.py" in t
    assert "start-stinky.ps1" not in t
    assert "pause" in t.lower()
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
    t = read("start_genesis.py")
    already = t.find("ALREADY RUNNING")
    stop_fn = t.find("def stop_owned_instance")
    assert already != -1
    assert stop_fn != -1
    assert "core_healthy" in t
    assert "--keep" in t
    assert "args.keep" in t


def test_start_writes_startup_log_and_redacts_secrets():
    t = read("start_genesis.py")
    assert "startup.log" in t
    assert "def redact" in t
    assert "API_KEY" in t and "TOKEN" in t and "PASSWORD" in t
    assert "150k" in t or "150_000" in t or "150000" in t


def test_start_detaches_via_cmd_start():
    t = read("start_genesis.py")
    assert "start-genesis-svc.cmd" in t
    assert "cmd START" in t or "Explorer job" in t
    c = read("scripts/start-genesis-svc.cmd")
    assert "start " in c.lower()
    assert "genesis-%NAME%" in c
    assert "run_genesis_service.py" in c
    assert "run-genesis-service.ps1" not in c


def test_start_health_uses_http_not_only_process():
    t = read("start_genesis.py")
    assert "http://127.0.0.1:8010/health" in t
    assert "http://127.0.0.1:3000/operator" in t
    assert "wait_http" in t
    assert "LIVE MARKET DATA" in t
    assert "LIVE GATE-1 EVENT" in t
    assert "UNKNOWN" in t


def test_browser_only_after_frontend_ready():
    t = read("start_genesis.py")
    assert "frontend is actually ready" in t
    open_at = t.find("open_operator")
    wait_at = t.find("http://127.0.0.1:3000/operator")
    assert wait_at != -1 and open_at != -1
    assert "browser launch failed" in t


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
    t = read("start_genesis.py")
    assert "--sync" in t
    assert "if not do_sync or skip_sync" in t


def test_default_start_stops_then_starts():
    t = read("start_genesis.py")
    assert "def stop_owned_instance" in t
    stop_at = t.find("stop_owned_instance()")
    start_at = t.find('start_detached("event-log"')
    assert 0 <= stop_at < start_at
    assert "taskkill" in t
    assert "not Genesis-owned" in t
    assert "8001" not in t[t.find("def stop_owned_instance") : t.find("def clean_broken_dists")]
    assert "foreach ($port in 8002, 8010, 3000, 8001)" not in t
    assert "utf-8-sig" in t
    assert "configure_stdio" in t
    assert "clean_broken_dists" in t


def test_sql_migrations_have_no_bom():
    for p in (ROOT / "services").rglob("*.sql"):
        data = p.read_bytes()[:4]
        assert not data.startswith(b"\xef\xbb\xbf"), str(p)


def test_start_does_not_sleep_then_exit():
    t = read("start_genesis.py").strip()
    assert not t.endswith("time.sleep(6)")
    assert "return 0" in t and "return 1" in t


def test_redact_line_contract():
    t = read("start_genesis.py")
    assert "def redact" in t
    assert "***" in t


def test_apply_launcher_exists_and_does_not_start_by_default():
    assert (ROOT / "APPLY-launcher.ps1").exists()
    assert (ROOT / "APPLY-launcher.cmd").exists()
    t = read("APPLY-launcher.ps1")
    assert "Restore-SearchPath" in t
    assert "install-desktop-shortcut.ps1" in t
    assert "reset --hard origin/main" in t
    assert "/d /k" in t
    assert "cmd.exe" in t
    # apply remakes the shortcut; stack start is opt-in
    assert "[switch]$Start" in t
    start_at = t.find("if ($Start)")
    assert start_at != -1
    assert t.find("start_genesis.py") > start_at


def test_start_restores_explorer_path_and_resolves_tools():
    t = read("start_genesis.py")
    assert "restore_search_path" in t
    assert "winreg" in t
    assert "find_docker" in t
    assert "find_npm" in t
    assert "NOT ON PATH" in t
    assert "Unblock-File" not in t
    assert "main.zip" not in t


def test_static_service_runner_is_allowlisted():
    assert (ROOT / "scripts/run_genesis_service.py").exists()
    assert (ROOT / "scripts/start-genesis-svc.cmd").exists()
    t = read("scripts/run_genesis_service.py")
    for name in ("event-log", "api", "sentinel", "discord", "collector", "entities", "web", "maintain"):
        assert name in t
    assert "urllib.request" not in t
    assert "main.zip" not in t
    s = read("stop-stinky.ps1")
    assert "run-genesis-service" in s or "run_genesis_service" in s
    cmd = read("Start-Stinky-OS.cmd")
    assert "start_genesis.py" in cmd
    assert "powershell" not in cmd.lower()


def test_installer_verifies_cmd_exe_after_save():
    t = read("install-desktop-shortcut.ps1")
    assert "VERIFY FAIL" in t or "still points at" in t
    assert "cmd\\.exe" in t or "cmd.exe" in t
    assert 'Name = "Genesis.lnk"' in t
    assert 'Name = "Stop Genesis.lnk"' in t
    assert 'Name = "Stinky OS.lnk"' not in t
    assert 'Name = "Apply Genesis Launcher.lnk"' not in t
    assert "Stinky OS.lnk" in t
    assert "OneDrive\\Desktop" in t
    assert "NO shortcuts written" in t
    assert "start_genesis.py" in t


def test_amsi_start_ps1_removed():
    assert not (ROOT / "start-stinky.ps1").exists()
    assert not (ROOT / "scripts" / "run-genesis-service.ps1").exists()
    assert (ROOT / "start_genesis.py").exists()
    t = read("Start-Stinky-OS.cmd")
    assert "start-stinky.ps1" not in t
    assert "start_genesis.py" in t


def test_stop_restores_path_for_docker():
    t = read("stop-stinky.ps1")
    assert "Restore-SearchPath" in t
    assert "Docker\\Docker\\resources\\bin" in t
    assert "Test-GenesisOwned" in t
