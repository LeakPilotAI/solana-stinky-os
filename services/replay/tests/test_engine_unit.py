"""Unit tests without live DB."""
from stinky_replay.config import settings


def test_defaults():
    assert settings.alert_min_score == 55.0
    assert settings.runner_volume_multiple == 2.0
