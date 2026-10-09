from copy import deepcopy
from types import SimpleNamespace
import pytest
from scripts import genesis_process_diagnostics as diag


def snapshot(tmp_path):
    root = str(tmp_path)
    rows = [(10, 0, 'python.exe', f'python.exe "{root}/scripts/run_genesis_service.py" --name collector'),
            (11, 10, 'python.exe', 'python.exe -m post_migration.cli'),
            (90, 0, 'python.exe', 'python.exe -m atlas.api')]
    return diag.owned_snapshot(SimpleNamespace(ROOT=tmp_path), rows,
                               lambda p: p*100, lambda p: 'C:/Python/python.exe')


def test_exact_roles_ancestry_creation_and_redaction(tmp_path):
    data = snapshot(tmp_path)
    assert [n['pid'] for n in data['nodes']] == [10, 11]
    assert data['nodes'][0]['role'] == 'supervisor:collector'
    assert data['nodes'][1]['parent_pid'] == 10
    assert data['nodes'][1]['creation_ticks'] == 1100
    assert 'post_migration.cli' not in str(data)


def test_inventory_order_and_unrelated_counts_do_not_change_identity(tmp_path):
    before = snapshot(tmp_path); after = deepcopy(before)
    after['nodes'].reverse(); after['inventory_rows'] += 1
    assert diag.verify_unchanged(before, after)['status'] == 'MATCH'


@pytest.mark.parametrize('field,value', [('creation_ticks', 9999), ('parent_pid', 90),
    ('image_path', 'c:\\atlas\\python.exe'), ('command_sha256', 'f'*64),
    ('role', 'supervisor:api')])
def test_same_pid_count_cannot_hide_reuse_or_changed_ownership(tmp_path, field, value):
    before = snapshot(tmp_path); after = deepcopy(before); after['nodes'][1][field] = value
    result = diag.compare_snapshots(before, after)
    assert result['changed'][0]['fields'] == [field]
    with pytest.raises(RuntimeError, match='not certified'):diag.verify_unchanged(before, after)


def test_owned_child_churn_records_both_identities_and_fails_closed(tmp_path):
    before = snapshot(tmp_path); after = deepcopy(before); after['nodes'][1]['pid'] = 12
    result = diag.compare_snapshots(before, after)
    assert result['added'][0]['pid'] == 12 and result['removed'][0]['pid'] == 11
    with pytest.raises(RuntimeError):diag.verify_unchanged(before, after)


@pytest.mark.parametrize('bad', ['missing', 'duplicate', 'clock'])
def test_stale_or_incomplete_snapshot_is_not_accepted(tmp_path, bad):
    before = snapshot(tmp_path); after = deepcopy(before)
    if bad == 'missing':del after['nodes'][0]['creation_ticks']
    if bad == 'duplicate':after['nodes'].append(deepcopy(after['nodes'][0]))
    if bad == 'clock':after['nodes'][0]['creation_ticks'] = None
    with pytest.raises(RuntimeError):diag.compare_snapshots(before, after)


def test_foreign_or_ambiguous_owned_descendant_fails_before_native_access(tmp_path):
    rows = [(10, 0, 'python.exe', f'python.exe "{tmp_path}/scripts/run_genesis_service.py" --name collector'),
            (11, 10, 'python.exe', 'python.exe -m atlas.api')]
    def forbidden(_):pytest.fail('ambiguous ownership must not reach native capture')
    with pytest.raises(RuntimeError, match='Unverified'):
        diag.owned_snapshot(SimpleNamespace(ROOT=tmp_path), rows, forbidden, forbidden)


@pytest.mark.parametrize('value', [None, 0, '123'])
def test_missing_creation_is_unavailable(tmp_path, value):
    rows = [(10, 0, 'python.exe', f'python.exe "{tmp_path}/scripts/run_genesis_service.py" --name collector')]
    with pytest.raises(RuntimeError, match='unavailable'):
        diag.owned_snapshot(SimpleNamespace(ROOT=tmp_path), rows, lambda _: value, lambda _: 'c:/python.exe')


def test_unexpected_native_executable_fails_closed(tmp_path):
    rows = [(10, 0, 'python.exe', f'python.exe "{tmp_path}/scripts/run_genesis_service.py" --name collector')]
    with pytest.raises(RuntimeError, match='differs'):
        diag.owned_snapshot(SimpleNamespace(ROOT=tmp_path), rows, lambda _: 10, lambda _: 'c:/node.exe')


def test_secret_arguments_are_never_in_snapshot(tmp_path):
    rows = [(10, 0, 'python.exe', f'python.exe "{tmp_path}/scripts/run_genesis_service.py" --name collector --token secret-value')]
    data = diag.owned_snapshot(SimpleNamespace(ROOT=tmp_path), rows, lambda _: 10, lambda _: 'c:/python.exe')
    assert 'secret-value' not in str(data) and '--token' not in str(data)
    assert len(data['nodes'][0]['command_sha256']) == 64


@pytest.mark.parametrize('bad', [None, {}, {'schema': 'genesis-native-process-snapshot-v1', 'nodes': []}])
def test_missing_inventory_coverage_fails_even_when_identical(bad):
    with pytest.raises(RuntimeError):diag.compare_snapshots(bad, bad)


def test_unchanged_but_stale_snapshots_cannot_certify_quiescence(tmp_path, monkeypatch):
    before = snapshot(tmp_path); after = deepcopy(before)
    monkeypatch.setattr(diag.time, 'monotonic_ns', lambda: before['captured_at_monotonic_ns'] + diag.MAX_SNAPSHOT_AGE_NS + 1)
    assert diag.compare_snapshots(before, after)['status'] == 'MATCH'
    with pytest.raises(RuntimeError, match='stale'):diag.verify_unchanged(before, after)


def test_future_acquisition_clock_fails_closed(tmp_path, monkeypatch):
    before = snapshot(tmp_path); after = deepcopy(before)
    monkeypatch.setattr(diag.time, 'monotonic_ns', lambda: before['captured_at_monotonic_ns'] - 1)
    with pytest.raises(RuntimeError, match='ordering'):diag.verify_unchanged(before, after)
