# EVM Reference Observation Operator Runbook

This runbook covers the explicit, read-only `genesis-evm-reference-observe` command added to the `stinky-api` package.

## Safety boundary

The command is observation-only. It does not accept private keys, wallets, signers, transaction payloads, approvals, admission decisions, opportunity scores, or execution authorization. It does not start a daemon or polling loop. Each invocation performs at most one explicit durable reference observation through the existing #249/#250 runtime seams.

Provider disagreement, quorum failure, malformed evidence, UNKNOWN evidence, or replayed/duplicate historical blocks continue to fail closed through the existing observation stack.

## Install

From the repository root, install the API package in the same Python environment used for Genesis:

```powershell
python -m pip install -e services/api
```

The install exposes:

```text
genesis-evm-reference-observe
```

## Trusted RPC configuration

RPC endpoints are supplied only through explicitly named environment variables passed with repeated `--rpc-env` arguments. The JSON payload never contains RPC URLs.

Each configured URL must:

- use `https://`,
- be non-empty,
- be distinct from every other provider URL,
- correspond to the chain named in the operator payload.

Example PowerShell session:

```powershell
$env:GENESIS_BASE_RPC_A = "https://YOUR-TRUSTED-PROVIDER-A"
$env:GENESIS_BASE_RPC_B = "https://YOUR-TRUSTED-PROVIDER-B"

genesis-evm-reference-observe `
  --input ".\operator\base-reference-observation.json" `
  --rpc-env GENESIS_BASE_RPC_A `
  --rpc-env GENESIS_BASE_RPC_B
```

Do not put credentials or RPC secrets in the JSON payload or commit them to the repository.

## Operator payload contract

The input file must contain the explicit historical observation payload validated by `ReferenceDexOperatorPayload`, including:

- chain and chain ID,
- factory, pool, token0, token1, and router addresses,
- pool discovery event metadata,
- pinned reference source records,
- exact historical `block_number`,
- `min_quorum`,
- scheduling interval/enabled state.

The command reuses the existing immutable #249 schedule/request types. It does not silently select a latest block or manufacture missing provenance.

## Output contract

Successful and failed invocations emit deterministic JSON. The operator response retains these safety markers:

```json
{
  "read_only": true,
  "execution_authorized": false
}
```

A successful observation may advance durable #250 completion state only after the underlying #248 observation succeeds. Duplicate or replayed block requests fail closed.

## Operational model

This command is intentionally manual/explicit. Production automation must not wrap it in a background daemon or automatic polling loop unless a later separately reviewed Genesis execution explicitly authorizes that architecture. Live trading remains locked.
