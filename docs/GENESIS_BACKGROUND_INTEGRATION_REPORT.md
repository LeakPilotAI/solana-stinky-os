# Inactive supervisor and Redis factory integration — partial certification

Base commit `12685e890c1984ade3267f553248e8e6f6f93a63`, existing
`chatgpt/443-intelligence-asof-dataset` branch. October 14, 2026 America/Chicago.
Final commit and exact test counts are recorded after certification below and in
the canonical roadmap/handoff. Production ownership remains AMBER.

## Actual integration and preserved behavior

`run_genesis_service.py` now has a default-None LAUNCH_OBSERVATION seam. With an
explicit trusted SupervisorObservation installed before main, private challenge
processing occurs before service dispatch and ownership-heartbeat publication.
Native descriptors are rechecked, heartbeat targets must match, and newly spawned
children require an explicit native callback. Secret bootstrap material never
enters heartbeat payloads. Errors latch HOLD and do not authorize termination.
With no installed context the normal runner behavior is unchanged. Combining this
mode with a cooperative supervisor rejects until their generation/capability
coupling is certified; no existing gate is bypassed.

`redis_accounting.redis_client` now has a default-None CLIENT_OBSERVATIONS seam.
It accepts only a typed inactive pool observer, rejects simultaneous protected
accounting configuration, and rejects installation after a legacy client was
issued. Every existing application call through that helper reaches the seam;
normal factories remain unchanged when it is None.

PoolObservations supports explicitly registered physical synchronous and async
connections. Each connection has its own private session, slot and processed
receipt bound to the signed request. Pool reuse re-probes epoch, ID, name and
socket identity and requires a fresh nonce-bound controller review/receipt.
Retired launches and replayed receipts reject. Silent reconnection rejects;
coordinated retirement and fresh registration remain required and incomplete.
A new pool alone does not retire stale controller records. A pool cannot silently
change owner PID or service/role. URL options
cannot bypass endpoint/DB/retry/capacity/timing constraints. Async application
read timeouts (including configured indefinite reads) are preserved; observation
probes have independent three-second deadlines. Unsupported sync read timeouts
reject rather than silently changing application semantics. This is observation,
not Redis write authority, ACL fencing or durable command accounting.

Only isolated observation registration was extended to optional discord, for its
existing discord-alerts factory role. Core startup selection remains exactly seven;
no optional service was launched or enabled.

## Coverage matrix

| Path | Evidence | Remaining limitation |
|---|---|---|
| Real runner main, ownership heartbeat, child creation | Native isolated entity workload, base Python and fresh Windows venv wrapper | Synthetic workload; not seven real services |
| Python wrapper/child/console-host observations | Bracketed native PID/creation/command descriptors; exact System32 conhost.exe / 0x4 exception | Not complete historical/kernel descendant-exit proof |
| Shared async factory redis-streams | Real Redis connection registration/reuse via central helper | Full publisher workload not started |
| api-manual-queue | Real async pool registration/reuse | No actual API/queue workload |
| collector-consumer / entity-consumer | Real async pool registration/reuse | No DB-backed service startup |
| sentinel-manual-consumer | Real async pool registration/reuse | BRPOP/work drain semantics remain uncertified |
| optional discord-alerts | Real async factory registration | Optional relay not started |
| Synchronous explicit pool | Real Redis registration/reuse; reconnect HOLD | Direct diagnostic constructors are not intercepted |
| Multiple physical connections | Separate sequential registrations/slots | Simultaneous pending registrations are not production-ready |
| Original desktop / per-service startup | Inspected, unchanged | Does not install the new private observation context |

The actual runner fixture copies the real source byte-for-byte into an isolated
repository, executes main with the real dispatch/spawn/heartbeat paths, and uses
only a synthetic entity module. The fixture bounds repeated work with a test-only
stop predicate and completion file. It does not certify graceful production stop.
Children complete naturally, with no broad process termination. Private proof is
consumed before normal runner output; secrets are absent from service logs/state.

A strengthened native fixture initially failed because Windows created conhost.exe.
The mismatch was diagnosed from redacted evidence, then handled only for the exact
System32 executable and observed 0x4 argument. Unknown descendants still reject.
No process-count shortcut or general descendant exemption was added.

Pool tests use real disposable Redis, but their native-controller callback is
explicitly mocked; the separate existing native client test verifies actual
PID/socket/server attribution. These proofs must not be combined into a claim of
native coverage for every real service client.

## Concurrent startup is still HOLD

The complete-client-inventory rule is unchanged. Simultaneous new connections can
observe each other as pending/unknown, so not all initial operations may pass.
A barrier test exercises that case and requires rejection rather than weakening
the global check. Supporting coordinated multi-client admission remains unfinished;
no capacity or concurrent production readiness claim is made.

## Preservation and independent staged-code verification

The runner and accounting files already contained CP77 edits. The exact original
working bytes were retained under logs/background-integration-before. Applying
only this execution's additions to those bytes reproduces the current working
files exactly. All other pre-existing modified files remain byte-identical; all
four pending migration files were untouched.

Only this execution's 19 hook lines in those two files are staged through a normal
reviewed Git patch. Original CP77 hunks remain unstaged. The exact staged runner
passed the unit/native cases independently of unstaged CP77 work. The
staged accounting module also passed isolated pool tests. No reset, stash, clean,
history rewrite, low-level Git object construction or unrelated staging occurred.

Final focused certification: **213 passed**, zero failures/skips, 102.74 seconds.
Independent exact-index certification: **10 supervisor cases passed** (35.87s)
and **21 pool cases passed** (27.30s). Final canonical suite: **1,707 passed,
16 skipped, zero failed**, exit 0, 166.87 seconds. One existing discord/audioop
deprecation warning. Compilation and working/staged diff checks passed.

Pool reuse additionally requires a fresh nonce-bound controller receipt, not only
a local socket probe. Retirement and replay tests cover stale launch/reply cases.
The controller review is read-only and cannot authorize a new connection or any
lifecycle action. Coordinated retirement and reconnect recovery remain unfinished.

Exact scoped files:

- docs/GENESIS_BACKGROUND_INTEGRATION_REPORT.md
- docs/GENESIS_BACKGROUND_MODE.md
- packages/stinky-core/src/stinky_core/transport/redis_accounting.py (new hook only)
- scripts/genesis_launch_provenance.py
- scripts/genesis_redis_client_provenance.py
- scripts/genesis_redis_pool_observation.py
- scripts/genesis_supervisor_observation.py
- scripts/run_genesis_service.py (new hooks only)
- tests/test_genesis_redis_pool_observation.py
- tests/test_genesis_supervisor_observation.py

Saved-state verification code and protected RDB copies remain unchanged. Previous
20,003-entry independent restores are artifact-only evidence; final acknowledged
shutdown-boundary completeness remains UNKNOWN. Production/Atlas container IDs,
states and start times are compared independently. No production startup, Redis
persistence/credential change, adapter activation or cutover is performed.

## Remaining blockers and exact next milestone

1. The real desktop launcher still does not provision this context; no private
   supervisor/controller transport is installed automatically.
2. Actual child entry points do not yet receive private generation capabilities.
   Child observation runs after spawn and is not a pre-execution write fence.
   Observational errors HOLD without killing an existing child. Integrate the
   existing inactive CP77 private bootstrap before authorizing any startup path.
3. Full ASGI, Node/web, maintenance and actual DB-backed worker workloads are not
   certified here. Complete root/wrapper/descendant and native Redis-client proofs
   jointly, not by combining unrelated fixture results.
4. All direct or third-party Redis constructors, async recovery paths, observer
   ownership, cross-process private receipt exchange and automatic reconnect
   reauthorization still need complete coverage. Sync tests use a local trusted
   exchange; they do not certify a bounded cross-process transport.
5. Concurrent registration, live writer fencing, ACL exclusion, retention/archive,
   acknowledged mutation accounting and BRPOP durable delivery remain HOLD. Do not
   bypass the existing broker or turn these observation callbacks into write gates.
6. Legacy env-token heartbeat behavior remains unchanged when the new context is
   disabled. Replace it only through a reviewed private bootstrap integration.
7. Redis continuous durability, full cooperative shutdown and saved final recovery
   boundary remain HOLD. Start/Stop/Restart/Gaming remain disabled; no gaming gain.

Next: certify private controller-to-supervisor-to-child bootstrap against actual
service entry points in isolation, then coordinate multi-connection attribution
without relaxing unknown-client rejection. Preserve all CP77/migration work and
the full V2/provenance/runtime/provider/#439/Intelligence Engine/Command Center/
product/alerts/SaaS/security roadmap. No live trading, signing, wallets or orders.

## Resumed private-child checkpoint — October 15, 2026

The next inactive increment adds a private Python child entry and signed final
dispatch-ready processing receipt, plus bounded complete-inventory Redis cohorts.
The earlier gaps above are historical; they are not all closed. Exact new coverage,
failure findings, preserved CP77 scope and remaining Web/Node/maintenance/wrapper/
child-factory HOLD conditions are recorded in
`docs/GENESIS_PRIVATE_CHILD_REGISTRATION_REPORT.md`. Production ownership remains
AMBER; no production startup or lifecycle authority is enabled.
