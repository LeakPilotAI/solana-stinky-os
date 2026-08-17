# stinky-core

Shared library for **Stinky OS**.

## Contents

- `events` – immutable event definitions (event sourcing)
- `transport` – EventTransport interface + Redis Streams adapter
- `quality` – Data Quality Layer (validation, rejection)
- `models` – shared domain models (entities, wallets, scores …) – growing

## Design rules (locked)

- Events are immutable.
- Business logic depends only on the transport interface (ADR-004).
- AI never invents scores (ADR-005).
- Every feature and model is versioned (ADR-006).
- Invalid events never reach intelligence services (ADR-007).

## Development

```bash
cd packages/stinky-core
pip install -e ".[dev]"
pytest -q --cov=stinky_core
```
