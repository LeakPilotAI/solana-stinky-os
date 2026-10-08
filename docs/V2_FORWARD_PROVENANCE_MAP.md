# V2 forward provenance visibility audit

This map distinguishes the clock's actual owner from the meaning a consumer may
attribute to it. Existing timestamps are not renamed, repaired, or backfilled.
Frozen V2 remains unchanged, and local diagnostics do not become experiment evidence.

| Stage | Timestamp owner and origin | Storage / code | Reliability and gap |
|---|---|---|---|
| Initial provider response / websocket receipt | No separate bound receipt clock | Sentinel migration watcher/RPC readers; collector chain client | Initial upstream receipt is unavailable. Provider block time is not network receipt time. |
| Domain event creation | Producer host UTC, default `Event.occurred_at` | `stinky_core/events/base.py`; immutable `events.occurred_at` | Authoritative for event construction where default is used, not first detection. Producers may supply their own occurred-at clock. |
| Migration detection | Sentinel structured logger timestamp after publication in `MigrationWatcher._handle` | `sentinel/migration_watcher.py`; retained Sentinel logs | Post-publication log emission is not initial detection. `DetectedMigration` has no explicit detection timestamp. Missing historical first-detection evidence cannot be reconstructed. |
| Migration anchor | Chain-provided block time when present; publisher falls back to host UTC when absent | `sentinel/publisher.py`, collector `service.py`, `migration_tracks.migration_at` | Mixed ownership: the stored field alone cannot prove chain-clock origin. Do not infer an on-chain clock from the field name. Changing this input during frozen V2 would affect semantics and is outside this change. |
| Event-log insertion | PostgreSQL transaction clock, default `now()` | `event-log/migrations/001_initial_schema.sql`: `events.ingested_at`; repository omits it from INSERT | Real database-ingestion timestamp, not first upstream ingestion or necessarily commit time. Replay uses conflict-ignore semantics; do not equate duplicate publication with a new initial ingestion. Not copied/bound into V2 plans. |
| Redis publication | Transport host UTC `EventEnvelope.published_at`; Redis stream ID owned by Redis | `stinky_core/transport/redis_streams.py` | Envelope/stream clocks are publication metadata, not source receipt. Republishing can create new transport metadata; V2 does not bind it. |
| Collector track insertion | PostgreSQL transaction clock default `started_at=now()` | Collector migration 001 and store `start_track` | Mutable projection/track-start proxy, not detection receipt or proof of continuous coverage. Collector event handling prefers block/occurred time and has existing host-clock fallbacks. |
| Market capture | Collector host UTC after response processing; Sentinel also persists snapshots | Collector `chain.fetch_market_snapshot` / `store.save_market_snapshot`; Sentinel `volume.py`; `market_snapshots.captured_at` | Capture timestamp is source-specific, not a separate ingestion/commit clock. V2 binds selected snapshots only for PAPER_PRICED; UNKNOWN/REJECTED do not bind observation clocks. |
| Score creation | Scorer host UTC captured once per pass | `run_intelligence_shadow_scorer.py`; `intelligence_shadow_scores.scored_at` | Pass clock, not per-row database insert/commit time. |
| Paper decision creation | Decision-worker host UTC captured once per pass | `run_intelligence_paper_decisions.py`; `intelligence_paper_decisions.decided_at` | Exact stored decision clock, not durable commit time. Preserved in frozen V2 plan. |
| V2 admission | PostgreSQL `clock_timestamp()` before guarded INSERT | Frozen V2 `planned_at`, entry/exit targets, plan hash | Exact frozen scheduling clock; guarded pre-entry insert. Do not substitute observer, event, or transport clocks. |
| Terminal recording | PostgreSQL `clock_timestamp()` pass cutoff | Frozen result `as_of`, `recorded_at`, result hash | Mature terminal evidence; paper snapshot proxy, not execution receipt or per-row commit time. |
| Collector interruption / restart | Supervisor host UTC; ownership heartbeat/start/restart/exit logs | `run_genesis_service.py`, `runtime-state-collector.json`, collector logs | Retained lifecycle observations exist. Hard kill/power loss may leave no final exit record; absence does not identify end time/cause. Heartbeat ownership and app health are separate. |
| V2 worker downtime / recovery | Existing child JSON success lines have no clock; generic failure/lifecycle logs incomplete | `logs/maintain.log`, independent V2 thread in supervisor | Exact pass boundary/history missing before instrumentation. Inter-pass gaps are not proven downtime; deliberate PC-off periods are not defects. |
| Source rate limiting | Host structured logger or HTTP error-line emission | Collector/Sentinel/entity logs; bounded health/detail diagnostics | Authoritative as a logged response/error observation where timestamped. Service-wide correlation is not mint-specific cause. Untimestamped traceback lines cannot be assigned a clock. |

## Smallest implemented improvement

Live read-only schema inspection at 2026-10-08T03:06:24.740992+00:00 verified
`events.ingested_at` and track `started_at` use `now()`, while snapshots have
`captured_at` (also a database default when omitted) and no `ingested_at` or
`received_at` columns. All 20 sampled latest migration events retained database
ingestion time; one had ingestion before producer occurred-at. This clock-order
contradiction is preserved, not aligned or repaired. Transaction clock and host
clock differences must not be reinterpreted as measured upstream latency or
as a proven runtime fault. The sample is bounded and not a full-history claim.

The nonfrozen service supervisor now wraps its existing V2 job call with
`genesis_pass_provenance.observe_pass`. It records START and FINISH/RAISED at the
supervisor's observation boundary, actual child return code, monotonic duration,
and an explicit ORDERED/REGRESSION/UNAVAILABLE wall-clock relation. It never
captures raw argv, stdout, exceptions, RPC addresses, credentials, mints, or prices.

Each pass has a fresh UUID; each observer instance has its own UUID and actual
supervisor PID. These identities are diagnostic, **not V2 observation sessions**,
and cannot increase adequacy. Duplicate event IDs are deduplicated; conflicting
duplicates are excluded and counted rather than choosing a convenient clock.
Missing/naive clocks remain null. Sink failure leaves the job's return/exception
unchanged and triggers no retries or cadence change. The existing single attempt
and 10-second sleep remain unchanged, covered by executing the actual loop body
against deterministic job and clock boundaries.

Local retention is explicitly bounded: `logs/v2-pass-provenance.jsonl` and one
owned `.previous.jsonl` file, at most 1 MB each under normal recorder ownership.
Only these diagnostic files rotate; canonical evidence, historical artifacts,
roadmap and ordinary service logs are untouched. The reader caps input at 1 MB
and output at 100 events, labels truncation/invalid/conflicting records, and never
turns a missing FINISH into an inferred end time or downtime duration.

Run `python scripts/genesis_pass_provenance.py` to read the current bounded file.
An absent file returns UNAVAILABLE. These observations have `experiment_evidence=false`;
they never enter V2 plans/results or change the certified summary/detail API/UI.

## Activation and remaining gaps

Instrumentation begins only when the updated maintenance supervisor starts
normally. A healthy collecting supervisor is not restarted merely to create
telemetry. Until that actual start, production pass timestamps remain unavailable;
test fixture records are not live evidence. No backfill or guessed activation time.

Future receipt/ingestion instrumentation would need an explicit source-event or
snapshot identity and clock ownership outside frozen V2, with separately reviewed
forward-only storage/retention. A detection clock must be captured at actual
receipt/detection, not reconstructed from logs after publication. Publisher
block-time fallback and mutable track projections are documented gaps; changing
their meaning or binding them into active V2 is not authorized by this audit.

After genuine new pass telemetry exists, audit retained completeness and clock
ordering before proposing a bounded operator presentation. Never claim an idle
interval is worker downtime, infer recovery from a successful exit alone, create
experiment sessions, relabel UNKNOWN, retune policy, or grant execution authority.
