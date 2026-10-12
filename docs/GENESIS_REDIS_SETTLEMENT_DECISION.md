# Checkpoint 74 — isolated settlement decision

Integrity certification passes. Capacity and production activation remain blocked.
This document does not certify production durability or desktop full Stop/Start.

## Root cause and repair

The native test first quiesced the route, then deliberately requested a new append.
The experimental dispatcher opened a provisional journal group before rejecting
that fenced admission. The raised exception poisoned the group journal. HOLD had
disabled credentials, but credential revocation then attempted to append its audit
record to that unusable journal. Server rejection handling and final cleanup raised
the same error again. This was abort completion failure, not proof of data loss.

Known fenced admissions now fail before a group opens, under the same broker lock.
They receive no command intent, dispatch permission or acknowledgement. Other group
failures still poison the journal and preserve unresolved evidence; they cannot
silently accept subsequent commands or claim settlement.

Credential revocation is independent of audit persistence. Exact known principals
are disabled, passwords and capabilities removed, and Redis ACL state independently
verified before reporting revocation. The status starts as HOLD/unverified on every
attempt. A failed journal is never written during cleanup. Verified revocation with
unavailable durable audit is explicitly HOLD, verified=true, durable=false; it does
not constitute a successful durable cleanup or authorize migration. A usable journal
must persist the revocation record before durable=true. Flush failure propagates and
leaves HOLD. Redis revocation or verification failure propagates without a success
claim. No broad credential reset or unrelated-principal targeting is introduced.

Recovery uses the existing strict trusted-head comparator. Unknown/partial tails
are not truncated or normalized away. Independently pinned revocation and verification
are required again during held recovery, which records a new durable recovery boundary.
Recovered routes remain HOLD; stale generations and credentials do not regain access.
An accepted command with a lost reply remains unresolved; recovery does not replay it
or declare it settled. Known BUSYGROUP rejection retains REJECTED_NO_EFFECT.

## Architecture decision

A. Existing serialized settlement remains the default. Repeated reference/sustained/
burst measurements were46.75/52.20/56.20 and52.05/55.45/54.80 appends/sec. Migration-heavy
trials were49.35/46.30/49.40 and77.00/72.85/74.00. A single reference pass is insufficient.

B. Bounded authenticated group commit is retained as **inactive isolated research**,
not selected for production. Only explicitly pinned checkpoint74 fixtures and native
fixture identities may enable it. Default disabled; eight queued authenticated peers,
four requests/group, eight metadata records and sixteen deferred publication actions.
No fill timer, physical mutation pipeline, relaxed ownership or early acknowledgement.
Custody payload fsync/readback precedes admission. Immutable ordered metadata commits
before receipt publication and producer release. Failures retain HOLD and unknown state.

C. Pipelined preparation with ordered settlement was evaluated, not implemented.
It requires reserved immutable command identities, preparation/route epoch recovery
and failed-preparation ordering. No measured justification exists for that larger change.

Serialized critical work remains dominant: a prior final group reference trial held
the broker critical section17.2081seconds/20second window, with broker CPU12.5781seconds.
Metadata fsync5502calls/2.6955seconds; payload fsync1304calls/0.6669seconds; native ownership
checks31886calls/4.1486seconds. Admission/settlement measurements are nested and must not
be summed as independent CPU time. Fewer flushes have not qualified end-to-end capacity.

Post-repair complete representative workloads, with three producers, two consumer paths
and a queue writer, measured acknowledged appends within the actual offered window:

| Trial | Reference | Sustained | Burst |
|---|---:|---:|---:|
| 8 |37.70|59.65|49.60|
| 9 |64.00|62.40|64.40|
| Required |71.71|143.42|286.85|

All six capacity gates FAIL. Trial8 p50/p95/p99 ACK seconds by phase:
0.03260/0.20269/0.29267;0.01886/0.18800/0.38321;0.03073/0.21311/0.36731.
Trial9:0.01606/0.19843/0.35339;0.01590/0.21253/0.36696;0.01715/0.18846/0.35347.
Peak consumer lag6 and5 respectively, then bounded catch-up to zero; no unresolved
commands at completion. Late settlements are excluded from window throughput. These
bounded trials do not prove long-running capacity or whole-host peak memory stability.
No improvement claimed; repeated variability and lower observed rates reject adoption.

## Certification and isolation

Final focused447passed/2skipped, canonical1355passed/5skipped, service1569passed/46skipped.
All exit0; existing service deprecation warnings retained. Group-specific22tests cover
fsync/partial-write/capacity/body failure, pre/post-commit crashes, identity changes,
partial receipt failure, immutable staging, bounded queue/backpressure, frozen admission,
independent revocation, failed audit flush and refusal to falsely verify live credentials.

Final native multi-process test:1passed in69.73seconds, no warnings; two complete
post-repair workload tests passed in65.64/68.26seconds. Native certification exercises normal post-quiescence rejection, lost reply,
process crash, prohibited trim, prohibited BRPOP, foreign identity, disconnect, bad auth
and server identity mismatch. Every scenario preserves strict ownership and held recovery.
Normal rejection creates no new intent; lost reply remains one unresolved operation;
prohibited trim/BRPOP return HOLD with nondurable revocation audit. New independently
verified held recovery cannot silently turn those statuses into write authority.

Two post-repair representative tests completed; encrypted archive readback/external
anchor and isolated AOF restart semantic recovery passed. Group/pending ownership and
delivery counts remain under the existing strict comparator. Repeated fixtures use new
stream and consumer-group names to preserve previous test evidence, not to delete it.
The repeated native fixture records a bounded pre-run lost-reply count and requires
exactly one additional item. Historical queue items and prior group state are retained;
a fresh group name isolates each run. An intermediate repeat exposed the former
absolute-count expectation; no queue was cleared and no replay assertion relaxed.
No assertion is relaxed for journal failure or missing acknowledgement.

Earlier final snapshot boundary:8024acknowledged commands; checksum-verified independent
RDB restore,2686bytes SHA2567247e94b22ac884471c09f7de836f3568c22741771dd0b92e814741e5fb19b5b.
The old fixture RDB was separately preserved before SAVE. No Redis protected-config
restriction was disabled. Scope remains INACTIVE_GATE_ONLY_NOT_LIFECYCLE_CERTIFICATION.

Production adapters remain inactive. No production pause, restart, cutover, credentials,
bindings, retention or configuration change. Original Redis container/storage/backups,
frozen V2 components and Atlas are untouched. The four historical pending migration
edits remain excluded from this checkpoint commit. Test containers/storage are retained.

## Remaining gates and lifecycle

Production Redis still disables AOF/automatic RDB and uses allkeys-lru: continuous
durability remains RED. No isolated result substitutes for production-specific proof.
Start remains core-only; full recovery AMBER. Stop remains forceful application-only;
graceful full-runtime certification RED. No live shortcut or full stop/start test occurred.

Required sequence remains: fence new work; account/drain or hold in-flight operations;
independently verify final durable snapshot and exact recovery; gracefully stop only
verified applications before exactly three owned dependencies; preserve identities,
volumes/evidence; restart same state, verify recovery and seven unique core services.
Atlas/Docker Desktop/test containers remain out of scope. Internet loss must degrade
external collection without resetting infrastructure. Abrupt-power-loss/unwritten-data
loss freedom is never guaranteed.

Next priority is a capacity decision, not activation or additional speculative tuning.
Other prerequisites: ledger epoch/head custody beyond50000records/64MiB; real coordinator
compact-custody rollback; complete native writer registration/fresh reauthorization;
noeviction/expiry/memory pressure, quarantine incremental-AOF and protected startup gates.
BRPOP remains rejected. Application/credential rollout and guarded Redis migration each
need separate approval. Cooperative supervisor/maintenance/child stop outside frozen V2,
exact dependency lifecycle and actual shortcuts need independent safety certification.
The full prior V2 descriptive review/provenance/reliability/#439/product/alerts/SaaS roadmap
remains in the same canonical continuity file; no live trading or retrospective retuning.
