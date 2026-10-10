import pytest

from scripts.redis_evidence_archive import EvidenceArchive, LIMIT
from stinky_core.transport.redis_accounting import AccountingError


def test_observed_production_rate_cannot_fit_one_minute_epoch(tmp_path):
    store = EvidenceArchive(tmp_path)
    with pytest.raises(AccountingError, match='capacity insufficient'):
        store.require_epoch_budget(peak_appends_per_second=71.71, epoch_seconds=60,
                                   measured_archive_bytes=1000)
    assert list(tmp_path.iterdir()) == []


def test_storage_fit_does_not_claim_throughput_or_authority(tmp_path):
    result = EvidenceArchive(tmp_path).require_epoch_budget(
        peak_appends_per_second=2, epoch_seconds=10, measured_archive_bytes=1000)
    assert result == {'required_archives': 20, 'available_archives': 128,
                      'required_bytes': 20000, 'throughput_certified': False,
                      'writers_authorized': False}


def test_existing_artifacts_count_against_both_budgets_and_are_preserved(tmp_path):
    path = tmp_path / ('a' * 32 + '.dpapi')
    path.write_bytes(b'protected')
    store = EvidenceArchive(tmp_path, max_archives=2, max_total_bytes=20)
    with pytest.raises(AccountingError, match='capacity insufficient'):
        store.require_epoch_budget(peak_appends_per_second=2, epoch_seconds=1,
                                   measured_archive_bytes=10)
    assert path.read_bytes() == b'protected'


@pytest.mark.parametrize('rate,seconds,size', [
    (0, 60, 1), (True, 60, 1), (float('nan'), 60, 1),
    (float('inf'), 60, 1), (-1, 60, 1), (1, 0, 1),
    (1, 3601, 1), (1000001, 1, 1), (1, 1, True),
    (1, 1, 0), (1, 1, LIMIT + 1),
])
def test_unavailable_or_out_of_bounds_measurements_fail_closed(tmp_path, rate, seconds, size):
    with pytest.raises(AccountingError):
        EvidenceArchive(tmp_path).require_epoch_budget(
            peak_appends_per_second=rate, epoch_seconds=seconds,
            measured_archive_bytes=size)


def test_unknown_storage_cannot_be_ignored_for_admission(tmp_path):
    (tmp_path / 'unverified').write_bytes(b'retain')
    with pytest.raises(AccountingError, match='unknown storage'):
        EvidenceArchive(tmp_path).require_epoch_budget(
            peak_appends_per_second=1, epoch_seconds=1, measured_archive_bytes=1)
