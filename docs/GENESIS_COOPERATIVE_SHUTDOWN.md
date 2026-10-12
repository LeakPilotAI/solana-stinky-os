# Checkpoint76 — inactive cooperative writer boundary

Registered-writer component certification is GREEN. Production integration and full
Start/Stop remain AMBER/BLOCKED. Nothing is installed into running services or shortcuts.

## Observed writer inventory

Repository call sites were inspected across services, packages and scripts. The shared
redis_client factory returns legacy pooled Redis clients when no protected grant exists.
Thus using that factory alone does not mean an authenticated broker is active.

| Owner / source | Mutations and work | Existing stop / acknowledgement boundary |
|---|---|---|
| event-log api.py → RedisStreamsTransport | XADD with MAXLEN; stream group creation/read/ACK transport | ASGI lifespan closes transport; legacy Redis reply, no live custody ledger |
| sentinel publisher.py → shared transport | migration/volume/outbox publication XADD and trimming | publisher close and task shutdown; retry/outbox behavior, legacy reply |
| sentinel manual_track.py | BRPOP destructive manual queue delivery, then publication | stop Event exists, but popped-item durable delivery remains unsupported |
| api track.py | LPUSH manual queue on HTTP request | per-request client close; no authenticated live acknowledgement accounting |
| collector service.py | XGROUP CREATE, XREADGROUP, XACK; background tracks/capture | stop cancels tracked tasks and closes clients; cancellation is not proof of drain |
| collector publisher.py → shared transport | XADD/retention | transport close; legacy reply, possible in-flight/retry ambiguity |
| entities service.py | XGROUP CREATE, XREADGROUP, XAUTOCLAIM, XACK; batch/funding tasks | stop cancels batch/funding tasks; close is not durable ACK proof |
| discord alerter.py (optional, absent) | Redis group consumption/ACK | must be inventoried if started; not silently omitted because outside core |
| maintain supervisor | schedules collector CLI/research/frozen V2/slow maintenance child jobs | three independent recurring loops; no cooperative supervisor command receiver |
| web | no application Redis client found in inspected sources | owned Node tree still needs graceful supervisor/child completion proof |
| optional paper services | separate producers/workers may create events through transports | absent in current core-only runtime; must inspect if enabled, never assume no writers |

No other direct Redis construction/mutation source was found in the inspected application
sources outside these factories/transports. This is source coverage, not verified native
ownership of every live socket. Live read-only Redis census observed15clients, including
the diagnostic client. Native client-to-process attribution remains UNVERIFIED. No raw
credentials, URLs, payloads or connection strings are stored in the public inventory.
An unknown writer must fail the protected boundary; no client-name or PID-count inference.

## Implemented contract

CooperativeParticipant is an explicitly constructed process-local participant bound to
the existing Runtime identity, server epoch, connection generation and role manifest.
It does not discover or authorize processes. A trusted authenticated controller supplies
the request; no unauthenticated shutdown endpoint, file signal, environment autoactivation
or writer-accessible control RPC was added.

The participant checks immutable ownership, requires a fresh request identifier and exact
manifest digest, latches Runtime shutdown, fences commands, durably records FENCING,
invokes the explicit synchronous producer/background admission hook, records DRAINING,
and awaits registered job tasks without cancellation/force killing. Remaining Redis
operations must settle through the existing ledger before QUIESCED is durably recorded.
Timeout, job failure, audit failure, lost reply, identity/route change or replay yields
HOLD. Final identity/deadline/fence checks run after the last audit commit. Audit failure
never produces a successful acknowledgement. It does not sleep a fixed period to claim
drain: task completion and the existing in-flight/ledger predicates control progress.

The async job context is the supervisor/service integration seam: wrap finite owned
work before beginning it; after fencing it cannot accept another job. Producer hooks
must actually disable subscriptions/scheduling. Existing unregistered loops and direct
legacy clients cannot be declared covered. New pool credential issuance and direct client registration are also refused after
the shutdown latch; existing client objects may still close. Runtime.resume_verified and route retirement/
reauthorization reject a latched shutdown generation. A verified Start must create a fresh
reviewed route/grant/runtime; this component cannot grant restart authority.

certify_participants is a trusted inactive controller join. It requires one durable ACK
per native registered writer, reconstructs manifests from the authoritative broker roles,
reads exactly the expected bounded phase sequence using a trusted hash-chain head,
drains the existing broker, requires independently verified and durably audited credential
revocation, and compares exact source censuses. It rechecks native identity, ACL exclusion,
connection membership and source stability after its own audit commit, under a bounded
deadline. Unknown/duplicate/missing writers, lost replies or contradictory evidence HOLD.
Participant journals are separate from the existing accounting journal; no recovery parser
or custody record format was weakened. Existing controller calls must use the shared
application-start.lock; the new seam performs no Start/Stop or container controls itself.

An ACK means PARTICIPANT_ONLY_NOT_FINAL_RECOVERY_BOUNDARY. A joined result means
REGISTERED_WRITERS_ONLY_NOT_FULL_LIFECYCLE. Neither proves all seven supervisors exited,
all production legacy clients accounted for, an RDB restore or safe dependency Stop.

## Certification

32behavioral tests cover concurrent jobs, new-job refusal, pending commands, unknown/
duplicate/missing participant evidence, stale requests, native identity replacement,
lost reply, job crash, timeouts without task cancellation, bad audit, route changes,
strict phase journal corruption, unknown connections and source payload changes.
Existing cooperative broker drain/final-snapshot/ownership tests remain required.

The explicit native fixture uses the existing pinned checkpoint74 Redis container,
independent storage and loopback test port. Three real processes use managed Redis roles
and independently observed native PID/birth identities. Two writers dispatch concurrently;
all participants durably acknowledge phases. The trusted controller joins ACKs, drains
nine settled commands, disables and verifies writer credentials, and tests a raw Redis
write bypass attempt after the boundary: Redis denies it and source fingerprints remain
unchanged. Phase journals are independently read back. Other native scenarios cover lost
replies, process crash, forbidden trim/BRPOP, foreign identity, disconnect and bad auth/server.
Held restart recovery and encrypted archive/AOF exact semantic restart checks remain strict.

No new test containers or volumes are required; the retained fixture is stopped again,
while all pre-existing production/Atlas/unrelated containers remain unchanged. No live
fault injection, production stop/pause, config/credential change or adapter activation.
Ordinary tests skip explicit Redis/native fixtures when absent; skips are not certification.

## Production integration gaps and next execution

Production adapters remain inactive. Participant job wrappers and admission hooks are
implemented and exercised in native service-like fixture processes; they are NOT wired
into seven production service loops or their current supervisors. Live Redis socket ownership
is not independently mapped. Collector/entities existing stop methods cancel tasks and must
not be substituted for the registered drain. Maintain scheduling/daemon threads and all
child jobs need authenticated cooperative request delivery and explicit phase acknowledgements.
Web/ASGI admission and child completion need coverage too. Unknown tasks/direct clients HOLD.

Next: nonfrozen actual service/supervisor admission hook integration and native complete
job/client inventory, with inactive transport first. Separately verify fresh Start reauthorization
and shared lifecycle lock integration. Do not activate protected adapters with their failed
capacity gates or silently relax them. BRPOP remains rejected, not durable delivery.

Production Redis still uses allkeys-lru, AOFoff/automaticRDBoff; no continuous durability
certificate. The final snapshot verifier still requires noeviction, complete writer closure,
source/restore equality, protected copies and a real checksum check. No changes to those
gates or production Redis. Full graceful application+three-dependency lifecycle remains
blocked until its separate snapshot/recovery/persistence/ownership/live-approval gates pass.
Start/Stop shortcuts unchanged. Atlas, frozen V2 and five zero-authority controls preserved.
No live trading, historical backfill, Redis cutover, AOF activation or eviction-policy change.
