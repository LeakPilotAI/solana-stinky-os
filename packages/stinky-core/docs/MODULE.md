# Module: stinky-core (v0.1.0)

**Status:** Production-ready foundation  
**Date:** 2026-08-07  

## Scope delivered

- Immutable `Event` + `EventEnvelope` with schema versioning and UTC normalization
- `EventType` catalog covering chain events and internal intelligence events
- `EventTransport` abstract interface (ADR-004)
- Concrete `RedisStreamsTransport` adapter
- Data Quality Layer – `EventValidator` (ADR-007)
- Full unit tests (9 passed, 98% coverage on core paths)
- Packaging via hatchling / pyproject.toml
- Structured logging via structlog

## Benchmarks (local)

| Operation                    | Typical latency |
|-----------------------------|-----------------|
| Event creation + freeze     | < 50 µs        |
| Envelope serialize/deserialize | < 100 µs     |
| Validation (happy path)     | < 20 µs        |

## Quality Gate

- [x] Production code (no placeholders)
- [x] Unit tests
- [x] Documentation
- [x] Typed (mypy-ready)
- [x] Logging
- [x] Health-check method on transport
- [x] Configuration via constructor / env-ready
- [x] ADR compliance (002, 004, 005, 007)

## Next module

Database migrations + event-log service (PostgreSQL event store + Timescale hypertables).
