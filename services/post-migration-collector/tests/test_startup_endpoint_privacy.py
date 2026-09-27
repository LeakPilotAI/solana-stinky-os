from unittest.mock import Mock

import pytest

from post_migration import cli
from stinky_core.evm_consensus import provider_fingerprint


def test_collector_boot_log_does_not_expose_redis_credentials(monkeypatch):
    endpoint = "redis://synthetic-user:synthetic-password@redis.example:6380/0?key=synthetic-query-key"
    monkeypatch.setattr(cli.settings, "redis_url", endpoint)
    monkeypatch.setattr(cli.sys, "argv", ["stinky-collector"])
    monkeypatch.setattr(cli, "_configure_logging", lambda: None)
    logger = Mock()
    monkeypatch.setattr(cli.structlog, "get_logger", lambda: logger)
    monkeypatch.setattr(cli, "_run_forever", Mock(side_effect=RuntimeError("synthetic stop")))
    with pytest.raises(RuntimeError, match="synthetic stop"):
        cli.main()
    event = logger.info.call_args_list[0]
    assert event.args == ("collector.booting",)
    assert event.kwargs["redis"] == provider_fingerprint(endpoint)
    assert "synthetic-" not in repr(logger.mock_calls)
