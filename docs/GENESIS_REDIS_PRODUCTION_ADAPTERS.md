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
