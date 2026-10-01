from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_recovery_launcher_is_bounded_and_no_rpc():
    s = (ROOT / "scripts" / "recover_interrupted_migration_tracks.py").read_text()
    assert "fail_stale_active_tracks" in s
    assert '"completion_manufactured": False' in s
    assert '"rpc_contacted": False' in s
    assert "fetch_trades" not in s
    assert "RECOVERED_MINT_SAMPLE_LIMIT = 20" in s
    assert '"recovered_mint_sample"' in s
    assert '"recovered_mint_set_sha256"' in s
    assert '"recovered_mint_list_truncated"' in s
    assert '"mints": mints' not in s
    c = (ROOT / "Run-Interrupted-Track-Recovery.cmd").read_text()
    assert "recover_interrupted_migration_tracks.py" in c
    assert "diagnose_unresolved_prospective_outcomes.py" in c



def test_unresolved_diagnostic_exposes_source_event_provenance_read_only():
    s = (ROOT / "scripts" / "diagnose_unresolved_prospective_outcomes.py").read_text()
    assert "source_event_id" in s
    assert '"source_event":dict(source)' in s
    assert "signature,producer,payload" in s
    assert '"candidate_mutated":False' in s
    assert '"rpc_contacted":False' in s
