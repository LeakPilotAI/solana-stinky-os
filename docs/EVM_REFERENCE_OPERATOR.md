# EVM Reference Observation Operator Runbook

This runbook covers the explicit, read-only `genesis-evm-reference-observe` command and the completely offline `genesis-evm-reference-preflight` command in the `stinky-api` package.

## Safety boundary

The observation command is observation-only. It does not accept private keys, wallets, signers, transaction payloads, approvals, admission decisions, opportunity scores, or execution authorization. It does not start a daemon or polling loop. Each invocation performs at most one explicit durable reference observation through the existing #249/#250 runtime seams.

The observation path always runs the same shared offline payload validation used by preflight before it constructs RPC observers or opens a database session. After observer construction, every configured provider must also successfully attest its registered chain through the existing read-only `eth_chainId` check before Genesis opens `SessionLocal` or invokes durable observation. A wrong-chain, malformed, unreachable, or otherwise non-attesting provider fails the entire invocation closed; Genesis does not discard a failed provider to salvage quorum.

The preflight command is stricter: it performs no RPC calls, requires no RPC environment variables, opens no database session, advances no durable trigger state, and performs no observation, scheduling, admission, scoring, signing, wallet, transaction, or execution action.

Provider disagreement, quorum failure, malformed evidence, UNKNOWN evidence, or replayed/duplicate historical blocks continue to fail closed through the existing observation stack.

## Install

From the repository root, install the API package in the same Python environment used for Genesis:

```powershell
python -m pip install -e services/api
```

The install exposes:

```text
genesis-evm-reference-observe
genesis-evm-reference-preflight
```

## Canonical payload template

Start from the repository template:

```text
operator/base-reference-observation.template.json
```

Copy it to an operator-owned working file such as:

```text
operator/base-reference-observation.json
```

Replace every `<REPLACE_...>` placeholder with evidence for the exact historical observation you intend to perform. The checked-in template is intentionally non-live: unresolved placeholders, malformed addresses/hashes, unsupported chains, and chain-ID mismatch fail closed.

Fields that must be replaced or reviewed include factory, pool, token0, token1, router, discovery event metadata, block/transaction hashes, pinned source metadata, exact historical block number, quorum, and scheduling fields. Keep `sources` explicit; do not manufacture or omit provenance.

The template contains no RPC URLs, credentials, private keys, wallet material, transaction payloads, admission decisions, opportunity scores, or execution authority.

## Offline preflight

Validate the copied payload completely offline before configuring providers:

```powershell
genesis-evm-reference-preflight `
  --input ".\operator\base-reference-observation.json"
```

A successful preflight emits deterministic JSON including:

```json
{
  "validated_offline": true,
  "read_only": true,
  "execution_authorized": false
}
```

Preflight never requires `--rpc-env`. It performs schema validation plus offline chain/address/hash/source validation only. It does not contact RPC providers, open `SessionLocal`, or invoke the durable reference observation runtime.

## Trusted RPC configuration

Only after preflight succeeds, configure trusted observation providers. RPC endpoints are supplied only through explicitly named environment variables passed with repeated `--rpc-env` arguments. The JSON payload never contains RPC URLs.

Each configured URL must:

- use `https://`,
- be non-empty,
- be distinct from every other provider URL,
- correspond to the chain named in the operator payload.

Before database or durable-runtime access, every configured provider is contacted with the existing read-only chain-attestation method. Every provider must return the expected chain ID. Any provider failure aborts the invocation before `SessionLocal`; failed providers are never silently removed to preserve quorum.

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

The observation command reuses the existing immutable #249 schedule/request types. It does not silently select a latest block or manufacture missing provenance.

## Output contract

Successful and failed invocations emit deterministic JSON. Operator responses retain these safety markers:

Observation and preflight failures use fixed diagnostic categories and messages.
They never echo exception text, malformed input values, credential-bearing RPC
endpoints, exception context, or local file paths. A failed command returns exit
code 1 (invalid command syntax retains exit code 2); preflight failures also retain
`validated_offline=false`. Invalid arguments use sanitized JSON instead of echoing
argument values to stderr; `--help` remains available. Check the input
schema/configuration for validation errors and provider/service availability for
I/O or RPC errors. Successful output contracts are unchanged.

```json
{
  "read_only": true,
  "execution_authorized": false
}
```

A successful observation also emits a `provider_attestations` array only after every configured provider has successfully completed the mandatory pre-attestation gate. Each row contains only:

- `provider`: the existing redacted `provider_fingerprint(...)` label,
- `chain`: the configured canonical chain key,
- `chain_id`: the remotely attested chain ID,
- `attested`: `true`.

The provider-attestation receipt is deterministic and sorted by the redacted provider label. Its row count equals the complete configured observer count. It never contains raw RPC URLs, URL paths, query strings, credentials, API keys, wallet data, signer material, transaction payloads, or execution authorization. If any provider fails attestation, the invocation fails before `SessionLocal` and no successful provider-attestation receipt is emitted.

A successful observation may advance durable #250 completion state only after the underlying #248 observation succeeds. Duplicate or replayed block requests fail closed. Preflight never advances durable state.

Apply `services/api/migrations/010_evm_provider_attestation_audit.sql` before using
the observation command. Successful triggered observations now append the full
redacted receipt to `evm_provider_attestation_audit` in the same transaction as
the evidence and completion state. Each version-1 record binds the chain, pool,
exact historical block, existing completion timestamp, configured provider count,
and sorted successful provider receipts. The completion timestamp retains the
existing runtime convention (the invocation's observation timestamp).

`load_provider_attestation_audit(session, chain=..., pool_address=...,
block_number=...)` retrieves and validates the exact historical receipt; missing
receipts return `None`. Earlier observations are not backfilled. UPDATE, DELETE,
TRUNCATE, and duplicate chain/pool/block inserts are rejected. Disabled/not-due
runs, replay rejection, failed observations, and rolled-back transactions leave
no audit record. Audit insertion failure rolls back the observation transaction.
The existing replay-state upsert and downstream quorum semantics are unchanged.

Retrieve a persisted receipt without contacting RPC providers:

```text
GET /v1/entity-graph/provider-attestations/{chain}/{pool_address}/{block_number}
```

All three identity fields are required. Chain and pool are canonicalized before
opening a read session. The block is an explicit non-negative historical integer;
`latest` is not accepted. The GET response includes the version-1 audit fields
and `read_only=true`, `execution_authorized=false`. Missing exact-block receipts
return 404, including observations made before audit storage existed. Malformed
identity or corrupted stored receipts return sanitized 422 responses. Retrieval
performs only a SELECT and never commits writes, backfills evidence, invokes RPC,
or changes observation/replay state.

## Operational model

These commands are intentionally manual/explicit. Production automation must not wrap observation in a background daemon or automatic polling loop unless a later separately reviewed Genesis execution explicitly authorizes that architecture. Live trading remains locked.
