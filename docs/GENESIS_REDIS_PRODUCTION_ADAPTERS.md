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


## Checkpoint 68: encrypted archive and held restart recovery

Checkpoint68 remains **PARTIAL / AMBER**. The new components are inactive. No
production process, pool, credential, Redis configuration or network binding was
changed. These components must not be mistaken for a completed retention protocol,
resumable broker bootstrap or production migration coordinator.

`redis_evidence_archive.EvidenceArchive` captures bounded atomic DB0 evidence using
the existing read-only Redis script. It retains actual DUMP bytes, stream IDs,
ordered duplicate field/value bytes, absolute expiry and complete consumer/group/
PEL metadata. Windows user-bound DPAPI protects payloads; no plaintext payload or
secret is written to the journal. Exclusive-new blobs are fsynced and read back,
decrypted and strictly validated before a separate trusted controller anchors
ciphertext/plaintext digests, route epoch, timestamp and receipt head. Source epoch
changes, corruption, missing data, failed fsync/anchor, unknown files, count/byte
exhaustion fail closed. Existing artifacts are never deleted or overwritten.
The archive is capped at128 blobs/1GiB and128MiB per encoded blob. It requires one
serialized controller; cross-process archive admission/rotation is not implemented.
DPAPI recovery requires the original Windows user protection material; it is not a
portable backup or hardware/power-loss guarantee. External anchors must themselves
be protected independently; copying a digest beside an untrusted blob is not proof.

Independent real Redis restore recovered two keys,18 stream entries and1 pending
entry from encrypted archived raw bytes into a fresh separate volume, with strict
payload/group/PEL equality. This is synthetic laboratory evidence, never V2 history.
Delayed archive capture explicitly cannot recover already removed IDs. There is no
retention exemption in the existing ledger: archived receipt checks do not replace
current source/candidate equality or authorize rollback. Archive capture is not yet
wired before every destructive retention action. MAXLEN, expiry and eviction still
block activation; original allkeys-lru and publisher retention remain unchanged.

The broker now fsyncs its initial native manifest and reviewed epoch/endpoint/
generation before issuance. `redis_broker_recovery.recover_held_boundary` requires
an independent trusted original journal head, validates all stage ordering and
identities, preserves every settled and unknown intent, revokes exact recorded
principals through a pinned authority and verifies revocation. It returns only an
immutable inspection ledger: registration, command dispatch and acknowledgements
are forbidden. All old bindings are inactive; next generation is reported but not
granted. Failed revocation/verification/fsync, unknown stages, contradictory receipts
or lost journal tails cannot return a recovered route. The original journal and
anchor remain required for repeated recovery; the new held-summary journal is not
self-contained writable state. No broker automatically resumes after restart.
Unknown accepted LPUSH remains ISSUED and prohibits rollback. Unrecorded principals
still require complete ACL inventory, not guessed ownership or broad revocation.

Real native three-writer fixtures exercised all nine prior scenarios plus held
journal reconstruction/revocation. Controlled full-AOF rewrite/fsync/restart retained
18 stream entries,19 list entries and the pending consumer ownership/count exactly.
This does not resolve the previous incremental replay loss of an empty consumer and
entries-read counter, nor certify arbitrary crash recovery. Strict comparison is
unchanged. No new multi-process coordinator cutover/rollback was performed.

The only inspected BRPOP consumer remains sentinel/manual_track.py. It is dormant
in normal core startup; managed BRPOP is rejected before dispatch. A durable queue
replacement would require a processing receipt/redelivery/duplicate contract absent
from that application. No implicit retries or silent semantics change were added.

### Explicit-loopback network preparation

`config/redis-loopback.compose.yml` is a future review-only overlay using !override
so the wildcard mapping is replaced, not appended. Local Compose config parsing
verified exactly127.0.0.1:6380 ->6379 without applying it. New isolated scope uses
only explicit127.0.0.1:16574..16577, reviewed checkpoint68 labels/native IDs/images/
independent volumes. Extra wildcard, empty HostIp, foreign mount or identity fails.
The actual production container still has empty HostIp on6380 and is rejected by
the new authority. Editing this overlay does not change an existing container.
Activation requires a separately approved, verified fresh recovery boundary and
new-container cutover: pin exactloopback mapping, independent durable storage,
complete writer fencing/ACK coverage/rollback and no competing volume writers.
Never apply a broad Compose operation or change production bindings in this task.

### Remaining activation blockers

1. Complete pre-disappearance archive custody/receipt epochs preserving actual
   MAXLEN/expiry semantics, serialized admission, independent anchor recovery and
   bounded capacity/rotation. A point-in-time archive alone is not this protocol.
2. Resumable broker bootstrap/route reauthorization with exhaustive native writers,
   complete ACL inventory and durable independent anchors. Held reconstruction is
   deliberately not a writable route.
3. Real multi-process coordinator cutover/abort/rollback certification with those
   archive epochs, preserving every acknowledged and uncertain mutation.
4. Strict consumer metadata recovery for required crash modes. Full controlled
   rewrite proof does not waive incremental AOF metadata loss.
5. Separately reviewed production loopback binding and graceful adapter activation.
   No live pool hot patch, restart, credential change or migration is implied.

All original containers/volumes, protected backups, frozen V2 files/evidence and
four pending58 edits remain preserved. Full graceful desktop Stop/Start is still
blocked on production durability and actual approved lifecycle certification.


## Checkpoint69: reconciled safety gates and AOF/ACL root cause

This checkpoint completes the supported stream custody and explicit route recovery
seams in isolation. Overall production readiness remains **AMBER / BLOCKED**. No
production actor, credential, network binding or dependency was changed.

| Blocker | Production seam | Invariant and minimum missing work | Certification |
| --- | --- | --- | --- |
| Stream trimming | core transport `redis_streams.py:publish`, MAXLEN20000 | Archive actual prior bytes and fsync its independent custody receipt before trimming dispatch. Implemented for positive MAXLEN with noeviction and no unaccounted expiry. | Real exact MAXLEN1 removed prior entries; their actual archived bytes still verify every receipt; corrupt, late or partial custody rejects. |
| Expiry | optional `discord_bot/alerter.py`, SET/EX48h | Value and expiry custody must precede installation/deletion. Still rejected; no silent optional activation. | Existing expiry and SET fail before permission; complete expiry/crash protocol not certified. |
| Eviction | original Redis allkeys-lru and384MiB limit | Existing target epoch demands noeviction; actual arbitrary eviction cannot be declared accounted from snapshots. Review policy/memory admission or prove equivalent complete custody before activation. | Evicting configurations still reject; production unchanged. |
| Broker restart | writer broker, factory/native registrations | Fresh independent authorization, current native manifest, generation and connection bindings; preserve all parent receipts/archives. Implemented inactive. | Three genuinely restarted native writers received generation2; old receipts and archive survived another held reconstruction. Stale generation, role mapping, PID reuse and grant reuse reject. |
| Rollback | coordinator move/rollback, production ACK bridge | Current fenced source/candidate equality plus every historical receipt's actual-byte coverage. | Actual cutover, eight new writes, rollback and restart preserved18 ACKs, group/PEL and archived trimmed payloads. Lost reply remains unresolved and accepted item survives restart. |
| Incremental AOF metadata | Redis7.4.9 loading, collector/entity group operations | Internal AOF EXEC must replay under safe quarantine before normal ACL fencing; never normalize away consumers/counters. Root cause/recovery proved. | Identical retained AOF fails under fenced default ACL, succeeds with TCP0/default authenticationOFF and narrowly permitted internal XCLAIM/SETID. Strict comparison unchanged. |
| BRPOP | dormant Sentinel manual_track consumer | Missing durable processing receipt/lease/redelivery semantics. Remains unsupported. | Real predispatch rejection; queue item remains. Normal core startup has no ManualTrackConsumer instantiation. |

### Automatic custody: limited but real

ProductionAcknowledgements now has an explicitly attached, default-none custody
hook. Before positive MAXLEN dispatch, ArchivedRetention requires settled earlier
operations, captures complete actual data with the existing encrypted archive,
fsyncs RETENTION_CUSTODY into the independent journal and checks all prior receipts
against current and archived bytes. Unproved history cannot be repaired by taking
an archive after disappearance. Corruption/failed anchor/unknown reply/stale epoch/
unaccounted expiry/capacity exhaustion holds rather than dispatches. MINID and
zero-length retention are not certified. The legacy membership gate is unchanged
when custody is absent. Current source/target metadata comparison is always strict;
historical payload custody is not a metadata or rollback waiver.

This protocol deliberately admits only a single physical operation at a time; a
competing unsettled operation fails closed. It still archives full bounded snapshots,
so throughput, capacity and long-running epoch rotation are NOT production-certified.
Bounds remain128archives/1GiB; no artifact deletion. No live workload was switched.
Expiry and arbitrary eviction are still unsupported and explicitly activation-blocking.

### Explicit route reauthorization

recover_held_boundary now verifies custody records and independent parent boundaries.
Every parent ACK and archive remains required. reauthorize_held_route checks settled
history, current native identity and principal inventory, refuses inherited ticket
state, requires fresh controller authorization and consumes an exclusive fsynced
source-boundary grant. A restarted writer needs explicit service-compatible role
mapping. Old bindings are never reused or unfenced. The next journal names its
parent head; a missing/contradictory parent cannot abandon historical writes. Fresh
separate connection credentials, native CIDs and generation2 are required before
mutation. No public RPC resume, environment activation or production bootstrap exists.
Grant location, parent resolution and independently protected anchors remain trusted
controller capabilities, not a claim that arbitrary caller-supplied callbacks are
cryptographically trusted. Production writer completeness is not inferred from labs.

### Proven incremental replay defect and safe recovery

The retained failed fixture is0dbc7074cc1e3b4845c9d801199ff22fbf3fc1e548bd445c493a24e38cc76b0d.
Its actual log contains alpha XCLAIM, XGROUP SETID with ENTRIESREAD1, and beta XCLAIM
with retrycount2. Thus the counter argument was not simply absent. Independent
same-image replay preserved payloads but lost alpha and returned UNKNOWN for1.
The original strict gate rejected these material differences.

Redis7.4.9's EXEC implementation rechecks permissions while executing queued
commands. The AOF loader uses a synthetic client; a fenced default ACL therefore
blocks the internal claim/counter transaction. This mechanism is supported by the
[pinned EXEC source](https://raw.githubusercontent.com/redis/redis/7.4.9/src/multi.c)
and [pinned AOF loader source](https://raw.githubusercontent.com/redis/redis/7.4.9/src/aof.c),
and confirmed by controlled replay of the same retained bytes, not merely inferred
from source. No data-loss normalization or individual historical counter repair.

The isolated recovery keeps default authentication OFF, disables TCP with port0,
and allows only XCLAIM/SETID loading on reviewed keys through the local protected
socket. One EXEC then restores the strict default write fence, enables the mapped
port and revokes/resetpasses bootstrap authority without external-command interleave.
The actual expose_readonly_after_quarantined_load function was exercised and strict
recovery matched both consumers/counter1/PEL/payloads. It returns only
READ_ONLY_VERIFICATION_REQUIRED, never authorizes writers. Full integrity and fresh
route authorization remain mandatory after read-only exposure. The original readonly
failure and all original AOF/config/ACL evidence are retained. Neither source image
nor strict recovery comparator was modified.

This is not deployed startup. Review the entire real AOF command inventory, scoped
loader privileges, socket/native ownership, atomic transition failure handling,
independent anchors and launcher integration before activation. Unknown commands or
material differences must keep writers blocked. No unrestricted default user on an
exposed port, no new broker credential policy bypass, no production restart/cutover.

### Isolated results and remaining production requirements

Eight new owned checkpoint69 containers on six independent volumes, all stopped and
retained; stage/front pairs share storage only serially, never simultaneously. The
checkpoint budget is exhausted: no more new69 fixtures or relabeling to evade it.
Three native actors per original nine scenarios plus three restarted actors; fresh
route12 ACKs and real exact trim; separate coordinator18 ACKs/8postcutover writes,
rollback and cold restart; one deliberately unresolved accepted LPUSH retained through
restart. Original102 containers, protected snapshots and Atlas were not controlled.
The coordinator's late clone check had a lab constructor error (ticket target field);
separate real negative certification used explicit username/password and passed.
Other lab-only counter/INFO-parser errors were fixed without weakening assertions;
failed artifacts retained. No claim that a failing harness invocation passed.

Remaining activation gates: complete expiry custody or explicitly reviewed exclusion;
review noeviction/memory admission; realistic concurrent throughput/epoch capacity;
production quarantine startup integration with real command inventory and failure
certification; exhaustive native writer/bootstrap/connection generation registration;
protected parent/grant/anchor lifecycle; explicit app-only activation approval and
subsequent separately approved durable cutover. BRPOP remains disabled/unsupported.
Existing production Redis still disables AOF/RDB and exposes emptyHostIp6380; future
loopback overlay remains unapplied. Full desktop graceful Stop/Start remains blocked.
No frozen V2, authority, Atlas, historical observation or product-policy changes.

## Checkpoint70 capacity admission — partial certification, activation blocked

The read-only demand sample in `logs/checkpoint70-demand.json` contains two
five-second intervals from the unchanged production Redis. One interval was idle;
the other observed 71.7122 XADD/s, 143.2247 XACK/s and 136.0335 XREADGROUP/s.
This short sample is observed demand, not a peak-load or adapter benchmark.
There was one DB0 key, zero current expirations, zero recorded expirations and
evictions, and approximately 29.35 MB used memory. The existing 384 MiB
allkeys-lru policy remains incompatible with the protected noeviction boundary.
Absence of past evictions is not evidence that eviction is safe.

`EvidenceArchive.require_epoch_budget` now performs a necessary offline storage
admission check using independently measured demand, a bounded planned epoch,
measured protected archive size and existing retained artifacts. It rejects absent,
quiet-only, nonfinite or oversized measurements and unknown storage. It preserves
all artifacts and never authorizes writers or certifies throughput. Call it before
issuing credentials in a future reviewed bootstrap; no production bootstrap calls
it yet. A positive diagnostic is not an atomic reservation or an activation token.

The current per-trimming-append complete archive has a maximum of128 files. At
the observed active rate that is less than1.79 seconds, even before byte quota,
fsync, parsing and accumulated historical verification costs. A60-second epoch
requires4303 archives and cannot fit. Increasing the quota or ignoring old receipts
is not a repair. Bounded custody handoff/rotation and realistic concurrent workload
certification are still required before enabling a normal production workload.

Expiry/eviction and destructive BRPOP remain explicitly rejected in protected mode.
Optional Discord TTL and the dormant manual-track BRPOP consumer cannot be admitted
as supported paths. Legacy production behavior is unchanged. Startup integration,
complete live writer registration, protected broker/anchor lifecycle, real memory-
pressure and concurrent throughput/recovery testing remain unfinished. The new
gate has deterministic behavioral coverage, not a complete end-to-end capacity
certificate. No new fixtures, production operations or activation were performed.

## Checkpoint71 — compact custody and dormant startup; activation BLOCKED

`AppendStore` replaces one full snapshot per append with encrypted, individually
anchored records in bounded8MiB segments. The existing128-segment/1GiB ceiling is
not increased. Each payload frame is fsynced and read back before a command intent;
the exact Redis entry, including ordered duplicate fields, is independently read
before the acknowledgement settles. One initial full snapshot covers the starting
dataset. Current source/candidate metadata still requires the original strict
recovery comparator. Missing payloads, contradictory IDs, partial writes, exhausted
storage, failed anchors or unanchored tails deny continuation. Recovered stores are
read-only; opening an existing directory as a writer is forbidden. There is no
automatic replay or deletion. Closed segments have independent fsynced hash seals.

Single-flight append admission uses authenticated pre-intent backpressure. Blocking
group reads remain concurrent so a5000ms consumer read cannot prevent its producer
from providing data. Explicit ambiguous replies mark the ledger uncertain and
revoke broker authority. Duplicate stream acknowledgement IDs cannot settle twice.
The broker may accept up to8 authenticated connections, while all ledger/identity/
credential decisions remain serialized. HOLD is published before waiting for that
lock; queued admissions and credentials cannot cross a known failure. Default
connection concurrency remains1. Compact completion sends the full original reply
once and reconstructs the identical canonical receipt bytes in the broker, retaining
the1MiB IPC limit. Fixed read-only CID/server probes retain both identity checks.

Readback reuses a single unbuffered descriptor while checking native file identity;
it does not cache plaintext or accept stale buffered contents. Local256-record
preparation measured124.72/s before this change and517.59/s afterwards. These local
figures are not end-to-end ingestion capacity. Encryption/fsync were not skipped,
and no new cryptographic dependency was installed.

The supported service runner now has an explicit `--protected-redis-grant` option.
Normal desktop startup does not supply it. A bounded user-protected grant must match
the current native process, broker PID/creation time, generation, reviewed Redis pins,
allowed roles, fresh expiry and independently reviewed GREEN admission decisions.
The first client installs the runtime before legacy client issuance; an empty,
missing, stale, unsupported or invalid protected grant cannot fall back to anonymous
Redis. Physical CID registration still precedes sealing any write permission.
Grants are trusted controller capabilities, not self-proving human approval: their
embedded HMAC key/signature is not an independent attestation against the same OS
user. Admission evidence and parent heads must be protected independently. No grant
was created for production, no credentials rotated, and no running service restarted.
The production controller/complete rollout remains uncertified.

### Explicit capacity acceptance and actual failures

Observed reference71.7122 appends/s is a short production observation, not a maximum.
The declared isolated targets are1x for20s,2x for20s and4x for5s,95% minimum accepted
throughput, p99 append acknowledgement<=1s, zero refusal and zero lag after bounded
consumer catch-up. Workloads use3 native producers,2 native group consumers and1
manual-queue writer,1100-byte payloads. A32-entry production sample measured839–970
bytes. Final consumers retain real collectorCOUNT20/entityCOUNT500 andBLOCK5000.
The earlier COUNT1/immediate-stop profiles are retained as conservative diagnostics;
they are not represented as the corrected production-shaped workload.

Final accepted throughput was48.1/s reference,47.75/s sustained and55.6/s burst;
p99 acknowledgements0.4574/0.4358/0.2916s, lag0 after catch-up, zero unresolved commands
and zero known refusals. All three throughput gates FAILED.2196 actual append records
and6865 settled operations survived exact trim, held reconstruction and strict AOF
restart. Custody occupied4271944 bytes in one segment; journal about10.07MB. Redis
memory, disk and stage timings are recorded in the protected workload artifacts;
full native-process peak RSS and long-duration stability remain unmeasured. No
activation certificate may be issued from the passing integrity test alone.

Eight new71 containers/volumes, all stopped and retained; peak<=2 active. Do not
create additional71 fixtures, relabel them, or delete evidence to evade this budget.
First benchmark failed on pre-dispatch backlog; later results retain capacity failure.
One wrapper failed when AOF rewrite was already active; later wrappers wait for its
completion and then request a fresh full rewrite before strict restart proof. That
failed invocation is not reported as successful. Native nine-scenario fencing/crash/
lost-reply/foreign-client/BRPOP regression passed in its separate owned fixture.
New custody was not certified through a real coordinator cutover/rollback; existing
deterministic coordinator regressions remain distinct. Parent history adoption,
independent durable-head lifecycle and closed ledger epoch handoff remain gates;
the ledger still has50000-command/64MiB limits. No indefinite-capacity claim.

### Controlled shutdown recovery audit and lifecycle position

The user's original dump.rdb SHA256 is
`d52413d13679c691fc69221ddc78e01a433cf9c755a4c91a9fd23b107b49635b`,6642152bytes.
Protected copies and two isolated restores matched1key/20002stream entries with
strict RDB comparison and no clock normalization. A reporting-only key_count error
occurred after those comparisons; independent retained-proof verification passed.
This certifies only that saved point. Production Redis loaded1key and is now accepting
new observations, but still disables AOF/automatic RDB and uses allkeys-lru. A named
volume or the old protected snapshot does not make current acknowledged writes durable.

Actual Start and Stop shortcuts still target the existing command wrappers. Seven
core services were already healthy after user startup; no recovery/restart was needed.
An earlier launch logged dependency inspection exit1 before container start timestamps;
engine readiness is a hypothesis, not an established error cause from redacted logs.
Stop remains application-only, with dependency stops performed manually by the user;
full graceful apps+three-dependencies lifecycle is not certified. Future activation
requires sufficient measured concurrent capacity, complete broker/head/epoch bootstrap,
noeviction/expiry and memory-pressure proof, actual custody coordinator rollback,
separate app/credential activation approval, then separately approved durable Redis
cutover and actual lifecycle certification. Keep healthy Genesis running.

### Checkpoint 72 — bounded custody transport and lifecycle gates

Production adapters remain disabled. No application/dependency restart, credential
change, Redis configuration change or cutover was performed. The four pending
migration edits remain separate from these changes.

Admission now indexes still-issued commands, retaining all historical receipts
and removing a pending entry only after its durable reply. Legacy fixture methods
cannot bypass the registered physical-command API. An authenticated pre-intent
conflict may wait for a receipt notification, releasing the broker lock for up to
eight 25ms waits. Each wake rechecks native owner, sequence, generation, sealed
credential binding and fencing. No physical dispatch or replay occurs during
that wait. A failed receipt, stale owner or new fence still HOLDs.

The optional named-pipe session transports at most256 requests and remains
default-one-request. Every reused request still checks native PID/creation and
broker sequence/authority. Frames authenticate session, direction, ordinal and
contents; replay/corruption/lost replies HOLD. Final close is authenticated and
cannot regain the route; normal bounded rotation reauthenticates. At most8 native
peer workers remain allowed. Controller startup does not automatically opt in.

Observed-entry metadata and its receipt may share one fsync while retaining their
original ordered hash-chain records. Both records must be durable before ACK or
pending removal. Partial write/fsync failure poisons the journal and preserves
custody/uncertainty; no recovery truncates or silently replays. Batches contain at
most8 metadata records, and the64MiB journal/50000-command limits remain unchanged.
This is not a batch of physical mutations or a delayed acknowledgement timer.

`FixedReadonlyEntryProbe` optionally sends only INFO/server, exact EVAL_RO/XRANGE
and INFO/server together through the scoped read-only observer. Both actual
remote epochs must match the prepared anchor. Custody is freshly decrypted and
the ordered payload bytes compared literally; no plaintext cache or skipped
decryption/identity/fsync gate. Managed writer mutation pipelines remain forbidden.

Real repeated trials retain the original targets71.7122/143.4245/286.849 appends/s,
95% accepted-throughput minimum, p99ACK<=1s, zero refusals and zero lag after bounded
catch-up. Three producers, two consumers and a queue writer use1100-byte records,
COUNT20/500 and BLOCK5000. Separate repeat streams preserve prior stream/group
data; no database reset or deletion. A first repeat failed on attempting to create
an already-retained group; its failure and artifacts remain, and later repeats
use explicitly scoped distinct streams rather than weakening that assertion.

Final fixed-probe trials measured34.95/45.45/48.4 and51.1/50.4/47.6 appends/s.
p99ACKs were0.3511/0.2625/0.2251 and0.1838/0.2287/0.3010s respectively. All throughput
gates FAILED; lower tails/request/flush counts are not a capacity certificate.
The earlier baseline36.6/38.95/34.8 and all intermediate profiles remain recorded;
host/run variation prevents claiming a sustained throughput improvement. Encryption
remains user-scoped DPAPI with the existing format and bounds. No dependency was
installed, quota raised or durability/receipt gate disabled.

Each successful trial independently checked exact trim, decrypted custody and
held reconstruction. Real same-fixture AOF restart/full semantic recovery passed
with appendfsync=always. The final retained fixture contains6 separate streams and
269 queue entries, with no pending group entries. All source/candidate comparisons
use the unchanged strict comparator, including only its previously declared AOF
activity-clock window. This does not certify production durability or complete
compact-custody coordinator rollback.

Exactly3 new72 fixtures/volumes were allowed, maximum1 active; all are stopped and
retained. Repeats used the current72 fixture's new streams/directories, preserving
every prior source/ledger/custody artifact. No old checkpoint fixture was relabeled,
reopened, removed or used as disposable storage. Future resource creation requires
a separately bounded plan; cleanup is not implicitly authorized.

The maintenance watchdog now verifies native owned dependency IDs and storage
through the existing project/service gate and shares the Start/Stop lock. It starts
only stopped exact IDs and verifies identity/config/storage afterward; no broad
container or process operations. Running supervisors were not hot-patched.
`verify_guarded_stop_snapshot` is an inactive read-only recovery gate that rejects
unfenced/unregistered writers, pending replies, changed server/custody evidence,
expiry/eviction, invalid copies, missing checksum or missing independent restore.
See [the lifecycle design and certification matrix](GENESIS_LIFECYCLE_CERTIFICATION.md).
Full graceful Stop remains unimplemented and blocked; existing shortcut behavior
is still application-only. Production controller rollout, epoch/head handoff,
adequate throughput and native lifecycle certification remain required.

## Checkpoint 73: complete settlement profiles and collection batching

Status: **AMBER components; RED capacity and production activation**. Production
adapters remain inactive. No production Redis cutover, credential change or
application restart was performed by this checkpoint.

The encrypted segment is fsynced and freshly read back before its anchor and exact
command intent share a single ordered metadata flush. Both metadata records must
be durable before admission returns. Flush failure retains the segment and holds
the route. An existing preparation cannot silently substitute for a new intent.
Receipt authentication, literal payload comparison, journal ordering, command
limits, replay refusal and all physical identity checks remain unchanged.

Append admission waiters are notified only when an append conflict can clear.
During a cooperative drain, every completed receipt notifies the controller.
`WriterBroker.drain_registered` fences server credentials, releases the broker
lock while already-issued receipts settle, and repeatedly verifies native owners,
participant completeness and actual connection inventory. Uncertainty, lost
fencing, changed identity or timeout retain HOLD. Its inspection callbacks require
their own bounded I/O; exceeding the deadline cannot produce a success result.
It is not exposed through writer RPC and does not stop processes or containers.

The bounded live stream sample contained 994 wallet-performance events, two
migrations, two quality events and two tracking-start events. Entities already
batch irrelevant acknowledgements. The collector now batches only classified
non-migration records, within its existing COUNT 20 boundary. Migration, malformed
and unavailable records retain their individual handler and acknowledgement.
Relevant processing finishes in original order before the ignored-record ACK, so
a lost no-op reply cannot strand an already-delivered migration. No SQL/research
side effect is deferred or replayed by this batching change. The running services
were not hot-patched or restarted to load later revisions.

### Measured complete Redis workload

Three native producers, two consumers and one queue writer use authenticated
receipts and actual Redis commands. Reference/sustained phases last 20 seconds;
burst lasts five. Representative trials offer 110% of the unchanged targets and
require 100% measured acceptance, p99 <= 1 second, no refusals/unresolved commands
and zero lag after bounded catch-up. Late settlements are reported separately,
not counted as within-window throughput. No sleep was added to fill consumer batches.
The relevant-event fixture measures Redis delivery/ACK costs, **not** external
RPC or SQL migration processing; it cannot establish whole-production capacity.

| Complete workload | Reference /s | Sustained /s | Burst /s |
| --- | ---: | ---: | ---: |
| Required targets | 71.7122 | 143.4245 | 286.8490 |
| Representative, collector per-entry ACK | 66.25 | 75.95 | 78.40 |
| Representative, collector batch ACK | 66.05 | 65.45 | 59.20 |
| Representative, repeated batch ACK | 72.35 | 58.90 | 65.80 |
| Migration-only Redis delivery/ACK | 62.20 | 59.35 | 67.20 |

One reference trial passed; repeated qualification did not. Sustained and burst
failed every trial. There is **no demonstrated reliable end-to-end throughput gain**.
The earlier all-per-entry profile reached 59.75/67.25/53.40 /s and located producer
time in authenticated serialized admission/settlement: about 18 of 20 seconds per
producer waiting on RPC. Sustained had 5,004 admission wakes and 11,054 fsync calls.
These are overlapping wall-time aggregates, not additive CPU measurements.

The representative sustained comparison explains why fewer ACKs did not solve
capacity: collector XACK calls fell from 1,522 to 653, but XREADGROUP calls rose
from 85 to 652 as faster consumers received roughly two records per read. Total
fsync calls per append remained approximately seven. Serialized delivery intents,
receipt settlement and single-flight append custody remain limiting. Encryption-only
or preparation-only throughput is not a substitute for this result.

Representative batch p50/p95/p99 ACK latency was 0.04155/0.07905/0.12505 seconds
in sustained traffic; the repeat was 0.04778/0.08320/0.12523 seconds. Peak sampled
pending intents were four; consumer lag reached five in the repeated batch workload
and 122 in migration-heavy traffic, then returned to zero. Sampled Redis memory
remained below 5.8 MB in these bounded trials. Whole-host peak RSS and long-running
closed-epoch/backlog stability remain unqualified.

Actual native crash/lost-reply/disconnect/authentication scenarios, encrypted
pre-intent crash retention, strict archived payload verification, registered drain
and same-fixture full-AOF rewrite/restart recovery passed in isolation. Pending
ownership/delivery metadata remained under the existing strict comparator. Three
checkpoint-73 throughput fixtures are retained stopped; repeats use distinct streams
and artifact directories in the current fixture without deleting prior evidence.

Next: resolve serialized group-delivery/settlement costs without artificial benchmark
waiting or weakening admission ordering. Complete independently anchored ledger
epoch handoff, real compact-custody coordinator rollback, native production writer
registration/reauthorization, expiry/eviction and quarantine-AOF gates before requesting
separate production rollout and guarded migration approvals. BRPOP remains rejected.
