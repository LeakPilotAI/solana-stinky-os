from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_formal_validation_launcher_starts_only_postgres_and_waits_for_health():
    t=(ROOT/"Run-Formal-Paper-Validation-Preflight.cmd").read_text()
    assert "docker version" in t
    assert "docker compose -p project-genesis up -d postgres" in t
    assert 'docker inspect stinky-postgres --format' in t
    assert '"healthy"' in t
    assert "180 seconds" in t
    assert "docker compose -p project-genesis up -d postgres" in t
    assert "Start-Stinky-OS" not in t
    assert "docker compose up -d" not in t.replace("docker compose -p project-genesis up -d postgres","")
    assert "formal_paper_validation_preflight.py" in t

def test_formal_validation_launcher_fails_closed_when_dependency_unavailable():
    t=(ROOT/"Run-Formal-Paper-Validation-Preflight.cmd").read_text()
    assert "docker_engine_unavailable" in t
    assert "postgres_start_failed" in t
    assert "postgres_not_healthy" in t
    assert '"database_modified":false' in t
    assert 'if "%ERR%"=="2"' in t
