# Checkpoint 66 — Inactive Redis writer adapters

## Scope and result

Adapters are implemented and behaviorally certified for the audited stream, list-insertion, expiry-marker and consumer-group operations. They are **default-off**. No application configures the managed factory, no running pool is replaced, and this checkpoint does not activate production accounting or certify production Redis durability. Existing factories retain their original options and behavior.

The migration coordinator and credential controller deliberately accept only owned isolated fixtures. A production bootstrap, credential broker and authenticated multi-process control plane remain unimplemented prerequisites; removing the isolation guards is not an activation procedure.

## Mutation inventory and semantics

| Operation | Authoritative application seam | Receipt and replay contract |
| --- | --- | --- |
| XADD, including MAXLEN | Shared RedisStreamTransport; sentinel/collector/entity/API publishers and script/outbox publishers using that transport | Exact returned ID and payload digest; no retry after uncertainty. Retention can delete acknowledged IDs, so the existing strict membership gate still blocks such a proof. |
| LPUSH | API manual-track queue | List insertion count and durable typed reply; repeated dispatch duplicates data. Full recovered list state remains necessary. |
| XGROUP CREATE | Shared transport, collector, entities, optional Discord | Group mutation; exact BUSYGROUP rejection is recorded as known no-effect. Other errors remain ambiguous. |
| XREADGROUP | Shared transport, collector, entities, optional Discord | Delivery changes group/PEL state even though the operation returns observations. Blocking duration is bounded. |
| XACK | Shared transport, collector, entities, optional Discord | PEL mutation; no replay merely because an acknowledgement was lost. |
| XAUTOCLAIM | Entity resolver pending reclaim | Changes ownership/delivery metadata and may report deleted IDs. All reply components are retained in the typed reply digest; complete semantic state comparison is mandatory. |
| XCLAIM | Explicit managed claim support and isolated certification | Ownership/delivery changes; strict pending ownership/count recovery proof. |
| SET with audited EX | Optional Discord deduplication marker | Expiry mutation; replay shifts expiry and is not treated as harmless. |
| BRPOP | Sentinel manual-track consumer | **Unsupported for activation.** Destructive delivery can leave an item only in process memory without a durable processing receipt/lease. Managed adapter rejects it before dispatch. Legacy behavior is unchanged. |

PING/INFO/CLIENT identity and audited read commands are distinguished from mutations. Unknown commands, pipelines, unregistered child clients and unsupported forms fail closed. Optional Discord and manual consumer coverage is not a claim that these services are running. The observed seven-service runtime retains legacy clients and anonymous Redis connections.

## Identity, intent and acknowledgement boundaries

A managed actor must provide verified PID, native creation time, repository/command fingerprints and service role. Native ancestry is captured before registration; native creation time/image is checked again before commands. Each client pins one physical connection, server epoch and route generation. A bound physical connection cannot reconnect. Parsed URL options are checked after client construction so URI settings cannot re-enable retries, switch the target or override sealed credentials.

The exclusive-new bounded journal fsyncs each hash-chained command intent before dispatch and each settled typed reply before exposing success. It stores argument/reply digests rather than secrets or raw payloads. Failed fsync, lost reply, malformed acknowledgement or uncertain Redis error puts the actor in HOLD. There is no automatic mutation replay. Recovery requires an independently trusted journal head; deriving an anchor from the same untrusted file proves nothing about a lost tail.

Runtime quiescence fences all supplied actors before draining. Server ACL fencing revokes mutation permissions as well. Missing actors, anonymous writers, unknown replies or identity/connection-set discrepancies prevent routing. Reauthorization closes old clients and increments generation but stays fenced until explicit verified resume. Coordinator fence enter/exit failures retain a recoverable state and diagnostic evidence rather than claiming a safe route.

The isolated credential controller issues unique read-only credentials, resets their password before counting/binding connections, then grants narrow role commands to the one verified CID. Credentials cannot be cloned after sealing. The complete default ACL policy, including categories and selectors, must prohibit writes. This server-side proof is necessary: client names and a Python ledger alone cannot stop bypass writers. The controller validates its admin target against the owned fixture port and volume; it cannot administer production.

## Isolated evidence

Eight new checkpoint66 containers on six separate volumes were created within the checkpoint retention budget; all are stopped and retained. No fixture shares production writable storage. Initial harness failures (immutable aclfile setting and redis-py's split ACL categories/commands) were diagnosed without production effects and preserved.

The successful end-to-end run used actual managed Redis clients: 18 acknowledged commands, 11 stream entries, eight post-cutover entries and one post-rollback entry. AOF recovery and subsequent rollback/restart preserved exact stream payloads and a pending entry with beta ownership/delivery count 2. Anonymous writes and sealed-credential cloning were rejected. An LPUSH accepted by Redis with a deliberately lost reply caused HOLD, denied rollback and preserved the unknown accepted item in candidate storage.

A final independent fixture recovered that forensic snapshot and two additional acknowledged writes. It preserved the original stream, pending metadata and unknown list item across restart. A lab-only cleanup helper accidentally shadowed the pinned image variable; ownership checks refused its stop. The same identified fixture was recovered using a protected copy of its lab ACL config, then independently verified and stopped. This was an isolated control-credential recovery, not a production credential change. The final two-receipt file count is not presented as an independently anchored production journal admission proof.

Artifacts under ignored logs/checkpoint66-* include protected snapshots, certification JSON, controllers and retained container identities. Preserve them; do not commit secrets/payloads or delete containers/volumes. Future tests must use a new authorized checkpoint namespace/budget, not exceed this checkpoint's eight-container limit. Eventual cleanup requires separate exact-identity authorization and confirmed independent recovery copies; stopped fixtures are not disposable merely because they are tests.

## Guarded activation plan — separate review required

1. Implement and certify a production-scoped least-privilege credential broker plus authenticated cross-process registration/quiescence control. Keep the current isolated coordinator guards intact. Explicitly enumerate every native writer, including ephemeral API/outbox clients, with service ancestry and connection generation. Extend verified ownership for optional services before enabling them.
2. Resolve BRPOP's durable delivery/processing gap or keep that functionality explicitly disabled. Do not silently change its delivery semantics. Define retention/receipt epochs for MAXLEN without exempting missing acknowledged payloads, and journal/ticket rotation/resource budgets. Current bounds fail closed (64 MiB journal, bounded command ledger/tickets); throughput, exhaustion and rotation need certification before long-running activation.
3. Review a bounded graceful Genesis application activation procedure separately. Checkpoint66 authorizes neither restart nor pause. Configure actors before creating any legacy pool; do not hot-patch running pools. Establish protected independent journal anchors and fail closed when process death loses acknowledgement evidence.
4. Verify native owners, all CIDs, server epochs, least-privilege ACLs and no anonymous mutation route. Fence server permissions and every actor before drain; unknown outcomes prohibit rollback. Preserve storage and unresolved evidence. Test broker failure, omitted actors, PID reuse, lost replies and partial activation under realistic multi-process load.
5. Activate only with explicit service-impact approval, then independently verify seven core services, endpoints, collection, frozen hashes and five zero-authority counters. Production registration/coverage must be demonstrated, not inferred from this lab.
6. Only afterward consider separately authorized Redis migration: fresh quiesced boundary, protected current snapshots, strict payload/PEL recovery, persistence/fsync/restart proof and rollback preserving post-cutover writes. Keep original storage. Full desktop Stop/Start certification remains pending production durability and actual authorized lifecycle tests.

Internet failures remain degraded external collection, never grounds for infrastructure reset. No historical backfill, frozen V2 changes, Atlas changes or trading authority are introduced.


## Checkpoint 67: inactive broker and guarded application recovery

The seven applications were absent at preflight, while all existing dependencies
were healthy. Authorized application-only recovery used the existing per-service
runner under the startup lock after ownership, schema and readiness checks. No
containers, configuration, credentials or production adapters were changed. The
startup boundary was 2026-10-10T05:22:15.899874Z (00:22:15 America/Chicago); seven
verified starts completed at 05:22:52.326841Z. Bounded log fingerprints and Windows
event availability were preserved before startup. Log activity ended around
October 9 22:44 Chicago; no proven cause was found. Maintenance timeout traces are
not evidence that all applications crashed. Outage cause remains UNKNOWN.

The new inactive redis_writer_broker module provides a central durable ledger
bridge for ManagedRedis through PipeProxy. It does not configure the global
factory, start a broker, or activate anything in application startup. Redis scope
pins include native container ID/image, exact project/service, mount and loopback
port. ProductionCredentials requires a separate ACL-manager principal without
ordinary data-command permission, exact role key scopes, verified native owner,
unique sealed connection credentials and complete ACL-principal inventory.
Production scope explicitly rejects fixture identities. Redis
ACL SETUSER is intrinsically powerful: the ACL manager is a trusted controller and
can grant privileges. This is reduced normal permission, not proof that a
compromised ACL administrator cannot escalate. No live credentials were changed.

The local Windows pipe uses bounded typed JSON (never unpickles incoming objects),
mutual nonce HMAC authentication and native process identity on both ends. Writers
verify broker PID/creation time; the broker verifies actual pipe peer PID against
its native manifest. Every physical command intent/reply still uses the fsynced
ledger. Central generation/epoch/endpoint checks reject stale routes; a ledger
registration without sealed credentials cannot authorize a mutation. Reply bytes
must match the typed reply. Server permission fencing precedes drain; missing
participants, native process loss, missing/unknown CIDs, lost replies, replayed IPC
or authentication failures cause HOLD and revoke controlled principals. There is
no automatic actor/process/reply replay and no public resume/routing shortcut.

Real isolated fixtures used three spawned native writers per scenario, not mocks.
Final scenarios covered normal writing/group claims, drain, an accepted LPUSH
with a lost acknowledgement, actor crash, unknown native peer, disconnect without
implicit reconnect, refused trimming/destructive pop, invalid HMAC and wrong
broker creation identity. Duplicate list insertions stayed distinct; no artificial
deduplication was introduced. BRPOP remains explicitly unsupported before dispatch;
no new queue lease, processing ACK or redelivery protocol is claimed. A consumer
crash cannot discard a popped item through this managed path because it cannot pop.

### Retention and recovery are still activation blockers

Inventory: shared transport appends use approximate MAXLEN 20000; optional Discord
SET markers expire after 48 hours; the current production configuration and existing
durable template use allkeys-lru. The only application BRPOP is the dormant manual
consumer. No application XTRIM/XDEL/explicit EXPIRE call was found in the inspected
write seams; unknown/admin mutations are not inferred absent merely from that scan.

RetentionBoundary currently demands noeviction, observed zero expiring keys and
untrimmed appends for a preservation epoch. It rejects MAXLEN/MINID and SET/EX before
intent or dispatch. The strict payload-membership gate remains unchanged. This is
a certified refusal mechanism, not complete archive-backed retention accounting.
It cannot activate against the unchanged normal production publisher semantics.
An independently certified archival/receipt-epoch protocol is still required to
preserve existing trimming/expiry behavior; neither behavior was changed here.

A real strict incremental-AOF restart failed: the empty alpha consumer disappeared
and group entries-read changed from 1 to UNKNOWN, while the surviving beta pending
entry and payloads remained. This was semantic metadata loss, not a harmless clock
or serialization exception. Protected before/after/difference artifacts are retained.
A deterministic regression requires rejection of these differences. Do not relax it.

Fresh isolated full-boundary tests waited for all actors to exit, completed AOF
rewrite with healthy persistence status, fsynced, then restarted the same fixture.
Exact payload/group/PEL recovery passed. This certifies controlled full-boundary
storage recovery only. It does not certify arbitrary incremental replay, abrupt
power loss, production durability, a new production route, or complete
multi-process coordinator cutover/rollback. The accepted unknown LPUSH was retained;
its missing acknowledgement still forbids migration or rollback despite successful
storage preservation.

Eight checkpoint67 fixtures are stopped and retained on eight separate volumes.
No original container, volume or protected recovery artifact was removed. The
checkpoint resource budget is exhausted; do not create more checkpoint67 fixtures
or evade the budget by relabeling them. Future isolated work must follow the
recorded retention/budget policy, preserve necessary evidence, and never perform
unauthorized cleanup. Exact results and IDs are in the ignored checkpoint report.

Remaining prerequisites: archive-backed retention epochs; strict preservation of
all group metadata across the required restart modes; durable broker restart and
reviewed native registration/bootstrap; explicit verified route reauthorization and
real multi-process coordinator cutover/rollback certification. Application
activation remains separately authorized only after these gates pass. No hot-pool
patching, production pause, Redis migration or full desktop Stop certification is
implied by this implementation checkpoint.

Additional verified ownership prerequisite: production Redis currently declares
HostIp empty for host port 6380. The broker requires an explicitly loopback-bound
endpoint and rejects this mapping. No port binding was changed. Resolve that
constraint through the separately reviewed infrastructure plan; do not falsify
inspect evidence or relax the pin to claim activation readiness.
