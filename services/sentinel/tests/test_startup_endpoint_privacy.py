import asyncio
from unittest.mock import Mock

import pytest

from sentinel import cli
from stinky_core.evm_consensus import provider_fingerprint


def test_startup_logs_fingerprints_without_endpoint_credentials(monkeypatch):
    endpoints = {
        "solana_rpc_url": "https://synthetic-user:synthetic-password@rpc.example/v2/synthetic-path-key?key=synthetic-query-key",
        "redis_url": "redis://synthetic-user:synthetic-password@redis.example:6380/0",
        "event_log_url": "https://synthetic-user:synthetic-password@events.example/synthetic-path-key",
    }
    for name, value in endpoints.items():
        monkeypatch.setattr(cli.settings, name, value)
    logger = Mock()
    monkeypatch.setattr(cli, "_configure_logging", lambda: None)
    monkeypatch.setattr(cli.structlog, "get_logger", lambda: logger)
    # Stop before constructing any external client; exercise the real boot log.
    monkeypatch.setattr(cli, "SolanaRPC", Mock(side_effect=RuntimeError("synthetic stop")))
    with pytest.raises(RuntimeError, match="synthetic stop"):
        asyncio.run(cli._run())
    event = logger.info.call_args_list[0]
    assert event.args == ("sentinel.starting",)
    for field, setting in (("rpc", "solana_rpc_url"), ("redis", "redis_url"), ("event_log", "event_log_url")):
        assert event.kwargs[field] == provider_fingerprint(endpoints[setting])
    assert "synthetic-" not in repr(logger.mock_calls)
