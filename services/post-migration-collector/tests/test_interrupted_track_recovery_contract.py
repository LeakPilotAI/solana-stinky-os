from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
def test_recovery_launcher_is_bounded_and_no_rpc():
 s=(ROOT/"scripts"/"recover_interrupted_migration_tracks.py").read_text()
 assert "fail_stale_active_tracks" in s
 assert '"completion_manufactured":False' in s
 assert '"rpc_contacted":False' in s
 assert "fetch_trades" not in s
 c=(ROOT/"Run-Interrupted-Track-Recovery.cmd").read_text()
 assert "recover_interrupted_migration_tracks.py" in c
 assert "diagnose_unresolved_prospective_outcomes.py" in c
