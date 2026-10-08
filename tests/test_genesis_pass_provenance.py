from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import pytest

SPEC = importlib.util.spec_from_file_location("pass_provenance", Path(__file__).parents[1]/"scripts/genesis_pass_provenance.py")
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)
T = datetime(2026, 10, 8, tzinfo=timezone.utc)


def observe(recorder, job=lambda: 0, clocks=(T, T+timedelta(seconds=1)), ticks=(1, 2)):
    cs, ms = iter(clocks), iter(ticks)
    return p.observe_pass(job, recorder, clock=lambda: next(cs), monotonic=lambda: next(ms))


def test_pass_boundaries_preserve_job_return_and_identity(tmp_path):
    recorder = p.Recorder(tmp_path/"passes.jsonl")
    calls = []
    assert observe(recorder, lambda: calls.append(1) or 3) == 3 and calls == [1]
    events = p.read_observations(recorder.path)["events"]
    assert [r["phase"] for r in events] == ["START", "FINISH"]
    assert events[0]["pass_id"] == events[1]["pass_id"]
    assert events[1]["elapsed_sec"] == 1 and events[1]["wall_clock_order"] == "ORDERED"
    assert events[1]["return_code"] == 3
    assert all(r["experiment_evidence"] is False for r in events)


@pytest.mark.parametrize("clocks,expected", [( (None, None), "UNAVAILABLE"), ((T, T-timedelta(seconds=1)), "REGRESSION"),
    ((T.replace(tzinfo=None), T), "UNAVAILABLE")])
def test_missing_naive_and_regressing_clocks_are_not_repaired(tmp_path, clocks, expected):
    recorder = p.Recorder(tmp_path/"passes.jsonl")
    observe(recorder, clocks=clocks)
    event = p.read_observations(recorder.path)["events"][-1]
    assert event["wall_clock_order"] == expected
    assert event["elapsed_sec"] == 1  # Monotonic duration remains independent.


def test_job_exception_and_sink_disconnect_preserve_execution_semantics(tmp_path):
    recorder = p.Recorder(tmp_path/"absent"/"passes.jsonl")
    assert observe(recorder) == 0
    assert p.read_observations(recorder.path)["status"] == "UNAVAILABLE"
    good = p.Recorder(tmp_path/"passes.jsonl")
    def disconnected_job(): raise ConnectionError("SECRET_SOURCE")
    with pytest.raises(ConnectionError, match="SECRET_SOURCE"): observe(good, disconnected_job)
    out = p.read_observations(good.path)
    assert out["events"][-1]["phase"] == "RAISED" and out["events"][-1]["return_code"] is None
    assert "SECRET" not in json.dumps(out)
    class BrokenSink:
        observer_id = good.observer_id
        def emit(self, event): raise OSError("disconnected")
    assert observe(BrokenSink()) == 0


def test_duplicate_events_and_restart_identities_do_not_create_sessions(tmp_path):
    path = tmp_path/"passes.jsonl"
    first, second = p.Recorder(path), p.Recorder(path)
    observe(first); observe(second)
    with path.open("a") as stream: stream.write(path.read_text().splitlines()[0]+"\n")
    out = p.read_observations(path)
    assert out["duplicate_events"] == 1 and len(out["events"]) == 4
    assert first.observer_id != second.observer_id
    assert out["downtime"] == "UNESTABLISHED" and "verified_runtime_sessions" not in out


def test_retention_rotates_only_owned_diagnostic_and_reader_is_bounded(tmp_path):
    recorder = p.Recorder(tmp_path/"passes.jsonl", max_bytes=1100)
    untouched = tmp_path/"historical.json"
    untouched.write_text("unchanged")
    for _ in range(10): observe(recorder)
    assert recorder.path.stat().st_size <= 1100
    assert recorder.path.with_suffix(".previous.jsonl").stat().st_size <= 1100
    out = p.read_observations(recorder.path, max_bytes=100, limit=1)
    assert out["bytes_read"] <= 100 and out["truncated"]
    assert untouched.read_text() == "unchanged"


def test_incomplete_and_invalid_records_do_not_expose_raw_data(tmp_path):
    path = tmp_path/"passes.jsonl"
    path.write_text('SECRET_URL\n{"observed_at":"made-up"}\n{"truncated":')
    out = p.read_observations(path)
    assert out["events"] == [] and out["invalid_lines"] == 3 and "SECRET" not in str(out)


def test_monotonic_clock_failures_remain_unavailable(tmp_path):
    recorder = p.Recorder(tmp_path/"passes.jsonl")
    observe(recorder, ticks=(2, 1))
    assert p.read_observations(recorder.path)["events"][-1]["elapsed_sec"] is None


def test_conflicting_duplicate_clock_is_not_silently_chosen(tmp_path):
    recorder = p.Recorder(tmp_path/"passes.jsonl")
    observe(recorder)
    event = p.read_observations(recorder.path)["events"][-1]
    event["observed_at"] = (T+timedelta(seconds=2)).isoformat()
    with recorder.path.open("a") as stream: stream.write(json.dumps(event)+"\n")
    out = p.read_observations(recorder.path)
    assert out["conflicting_event_ids"] == 1 and len(out["events"]) == 1
    assert out["downtime"] == "UNESTABLISHED"


def test_invalid_identity_type_is_unavailable_metadata_not_reader_crash(tmp_path):
    recorder = p.Recorder(tmp_path/"passes.jsonl")
    observe(recorder)
    event = p.read_observations(recorder.path)["events"][-1]
    event["observer_id"] = 123
    recorder.path.write_text(json.dumps(event)+"\n")
    out = p.read_observations(recorder.path)
    assert out["events"] == [] and out["invalid_lines"] == 1


def test_service_wrapper_executes_real_loop_with_same_attempts_and_cadence(tmp_path):
    import ast
    source = (Path(__file__).parents[1]/"scripts/run_genesis_service.py").read_text()
    tree = ast.parse(source)
    loop = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "intelligence_execution_v2_loop")
    calls, sleeps = [], []
    class Sleep:
        def sleep(self, seconds): sleeps.append(seconds); raise SystemExit()
    context = {"observe_pass": p.observe_pass, "pass_recorder": p.Recorder(tmp_path/"passes.jsonl"),
               "run_job_with_retry": lambda argv, **kw: calls.append((argv, kw)) or 0,
               "py": "python", "root": Path("repo"), "time": Sleep()}
    exec(compile(ast.Module(body=[loop], type_ignores=[]), "service-loop", "exec"), context)
    with pytest.raises(SystemExit): context["intelligence_execution_v2_loop"]()
    assert calls == [(["python", str(Path("repo/scripts/run_intelligence_execution_v2.py"))], {"attempts": 1})]
    assert sleeps == [10]
    assert [r["phase"] for r in p.read_observations(tmp_path/"passes.jsonl")["events"]] == ["START", "FINISH"]
