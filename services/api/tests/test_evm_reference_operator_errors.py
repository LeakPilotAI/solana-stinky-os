import json

import pytest

from stinky_api import evm_reference_operator_cli as observe
from stinky_api import evm_reference_operator_preflight_cli as preflight
from stinky_api.evm_reference_operator_errors import serialize_operator_failure
from stinky_core.evm_rpc import EvmRpcError
from test_evm_reference_operator_cli import payload


SECRET = "SYNTHETIC_OPERATOR_SECRET_261"
ENDPOINT = f"https://rpc.example/private/{SECRET}?key={SECRET}"


@pytest.mark.parametrize("module", [observe, preflight])
@pytest.mark.parametrize("kind", ["missing", "unknown"])
def test_argument_errors_do_not_echo_secret_arguments(monkeypatch, capsys, module, kind):
    def forbidden(*args, **kwargs):
        pytest.fail("argument error reached input file")
    monkeypatch.setattr(module.Path, "read_text", forbidden)
    args = [] if kind == "missing" else ["--input", ENDPOINT, "--" + SECRET, ENDPOINT]
    if module is observe and kind != "missing":
        args += ["--rpc-env", "RPC_A", "--rpc-env", "RPC_B"]
    assert module.main(args) == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    assert SECRET not in captured.out
    assert json.loads(captured.out)["error"] == "ArgumentError"


@pytest.mark.parametrize("module", [observe, preflight])
@pytest.mark.parametrize("kind", ["validation", "json", "file", "evidence"])
def test_command_input_failures_never_echo_values_or_paths(monkeypatch, capsys, module, kind):
    valid = payload().model_dump(mode="json")
    if kind == "validation":
        valid["chain_id"] = ENDPOINT
        raw = json.dumps(valid)
    elif kind == "json":
        raw = '{"' + SECRET + '": '
    elif kind == "evidence":
        valid["chain"] = ENDPOINT
        raw = json.dumps(valid)
    else:
        raw = ""
    def read(*args, **kwargs):
        if kind == "file":
            raise FileNotFoundError(2, "not found", f"/private/{SECRET}.json")
        return raw
    monkeypatch.setattr(module.Path, "read_text", read)
    def forbidden(*args, **kwargs):
        pytest.fail("invalid input reached RPC or database")
    monkeypatch.setattr(observe, "build_cli_observers", forbidden)
    monkeypatch.setattr(observe, "SessionLocal", forbidden)
    args = ["--input", f"/private/{SECRET}.json"]
    if module is observe:
        args += ["--rpc-env", "RPC_A", "--rpc-env", "RPC_B"]
    assert module.main(args) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert SECRET not in captured.out and "https://" not in captured.out and "/private/" not in captured.out
    result = json.loads(captured.out)
    assert result["ok"] is False and result["read_only"] is True and result["execution_authorized"] is False
    assert result["error"] == {"validation": "ValidationError", "json": "JSONDecodeError", "file": "OSError", "evidence": "ValueError"}[kind]
    if module is preflight:
        assert result["validated_offline"] is False


@pytest.mark.parametrize("exception", [EvmRpcError(ENDPOINT), RuntimeError(ENDPOINT), ValueError(ENDPOINT), OSError(ENDPOINT)])
def test_observation_runtime_failure_is_sanitized(monkeypatch, capsys, exception):
    monkeypatch.setattr(observe.Path, "read_text", lambda *args, **kwargs: payload().model_dump_json())
    async def fail(*args, **kwargs):
        raise exception
    monkeypatch.setattr(observe, "execute_operator_payload", fail)
    assert observe.main(["--input", "fixture.json", "--rpc-env", "RPC_A", "--rpc-env", "RPC_B"]) == 1
    output = capsys.readouterr().out
    assert SECRET not in output
    assert json.loads(output) == serialize_operator_failure(exception)


def test_unknown_exception_name_and_string_are_never_serialized():
    class HostileError(Exception):
        def __str__(self):
            pytest.fail("exception string must never be evaluated")
    HostileError.__name__ = SECRET
    result = serialize_operator_failure(HostileError())
    assert result["error"] == "RuntimeError"
    assert SECRET not in json.dumps(result)
    assert serialize_operator_failure(ValueError(SECRET)) == serialize_operator_failure(ValueError("different input"))


@pytest.mark.parametrize("module", [observe, preflight])
def test_success_output_compatibility(monkeypatch, capsys, module):
    monkeypatch.setattr(module.Path, "read_text", lambda *args, **kwargs: payload().model_dump_json())
    args = ["--input", "fixture.json"]
    if module is observe:
        expected = {"triggered": False, "read_only": True, "execution_authorized": False}
        async def success(*args, **kwargs):
            return expected
        monkeypatch.setattr(module, "execute_operator_payload", success)
        args += ["--rpc-env", "RPC_A", "--rpc-env", "RPC_B"]
    else:
        expected = module.validate_operator_payload(payload())
    assert module.main(args) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, **expected}
