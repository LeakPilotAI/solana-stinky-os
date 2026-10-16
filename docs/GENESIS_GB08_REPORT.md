# GB-08 global maintenance fencing review

October 15, 2026 America/Chicago. Base f7fd428ca9306ec64bf6a52f4075c5c39959b7f6.
Branch chatgpt/443-intelligence-asof-dataset. Overall AMBER/HOLD: certified scope
is process-local managers sharing one trusted authenticated launch registry.
No global write, snapshot, shutdown, production ownership or lifecycle authority.

## Proven gap and smallest repair

Previously MaintenanceDrain fenced only cycle(). Direct manager.loop/job calls,
including another MaintenanceObservation using the same launch registry, bypassed
that fence. Drain inspected only its own manager and registered cycles.

Managers now share a condition/lock and admission boundary keyed by the exact
trusted LaunchObservations registry. Both loop and job admission check the fence
under that lock. Explicit isolated=True controller activation binds the full
private authenticated supervisor challenge; a changed challenge fails closed.
request_drain atomically fences new manager admissions before returning its signed
session/generation/nonce request. Existing jobs may complete; they still require
private child completion, native exit/descendant retirement, source and job identity.
An admitted loop cannot create a new job after drain. A rejected new admission does
not poison an already-admitted job. Failed/unknown jobs latch shared HOLD.

Drain waits on all managers in this registry, including direct callers and
replacement managers. Every participating manager must have an independent
retirement witness. Shared active-loop and native-PID claims reject duplicate
ownership across managers, not just within one object. Zero active loops/owner claims plus the independently supplied
zero-child/unresolved/admission-closed witness are required. Timeout remains HOLD.
Completed generations cannot reopen. A fresh authenticated generation is accepted
only after the preceding boundary is CLOSED and all tracked managers idle.
Default-disabled controllers neither claim nor reopen a generation. No executor,
process signal, production activation, schedule, retry or frozen worker change.

## Admission and writer inventory

| Path | Boundary coverage | Remaining limit |
|---|---|---|
| MaintenanceDrain.cycle -> manager.loop -> manager.job | Shared atomic manager admission; authenticated generation | Process-local only |
| Direct MaintenanceObservation.loop/job | Same fence, including admitted loop/new-job race | Arbitrary code outside job context is not a tracked operation |
| Alternate/replacement manager using same LaunchObservations | Shared boundary; cannot reopen; included in drain | New independent registry is not an authorized member |
| SupervisorObservation.loop/job/child_command/child_started | Delegates to manager; native supervisor/private child checks unchanged | Real desktop bootstrap not installed or executed |
| run_genesis_service supervisor_loop + retry helper | Existing optional observation routes through manager | Runner is preserved CP77 pending work, unchanged |
| Slow loop learn-success/recompute-performance | Exact manifest/source/private child and retirement | All real-job interrupted recovery remains HOLD |
| V2 loop frozen worker + pass recorder | Same admission; frozen code unchanged | Pass recorder/local file writes not a global SQL/Redis fence |
| Research scorer/decisions/V1 plans | Same authenticated job manifest | No new SQL replay authority |
| Research watchdog_tick/dump_runtime | Outer loop visible while admitted | CP77 run_admitted_job(dependency-watchdog) is a separate optional path; watchdog controls/health/log writes are not individual jobs in this manager; no global closure claim |
| Separate LaunchObservations/controller or another OS process | NOT covered by this registry fence | Must remain HOLD; no cross-process authority or durable claims |
| Legacy direct Redis/SQL clients, optional workers, raw subprocesses | NOT inventoried to complete live socket ownership | Global Genesis/Redis/PostgreSQL write quiescence remains HOLD |

Actual production supervisor_loop wraps long-lived loop lifetimes. It does not
magically cause those loops to return when a manager drain is requested. No new
cooperative signal is installed in production. Full supervisor exit and all helper
identity/socket coverage remain unverified. Kernel job membership is descendant
closure evidence, not individual descendant authentication. The unchanged CP77
native witness remains untracked and is not packaged in this commit.

## Bypass and failure matrix

Behavioral tests cover direct manager admission after drain, replacement managers
before/after drain, duplicate controller claims, direct jobs admitted before drain,
new jobs from already-admitted loops, twenty concurrent admission/drain races,
failed replies, unknown job identities, duplicate native owner claims across managers, missing retirement, disabled controls and
closed-generation reopening. Existing generation replacement, malformed signatures,
replayed drain, clock regression, timeout, incomplete idle proof and transaction
COMMITTED/ROLLED_BACK/AMBIGUOUS tests remain required. No ambiguous job auto-replay.

Native fixture repeats three concurrent real command entries across two waves,
requires >=3 independently observed simultaneous SQL waiters each wave, private
child authentication and zero kernel descendants before successful drain. Adds
actual direct-manager rejection after native job closure. Six-entry GB-06 native
regression remains separate; not all commands run in one complete native supervisor.
Isolated SQL fault tests preserve transaction-level ambiguity and no automatic replay.

## Preservation and resources

Original 29 pending tracked modifications, four migration edits and CP77 remain
byte-identical. No production Genesis/Atlas service or container is started.
Only previously pinned PostgreSQL 16606 and Redis 16603 tmpfs fixtures are reused,
after exact ID/image/label/loopback/storage and previous SQL-export hash checks.
No production storage is mounted, no credentials reused, and no container/volume
is deleted. Test SQL exports are retained before normal smart fixture shutdown.
No forced cleanup or kill fallback. Saved RDB copies remain unchanged; no new
production recovery/durability/evidence/counter claim is made while Genesis is stopped.

## Certification results

Final focused/native/Gaming/watchdog/supervisor suite: **154 passed, 0 failed,
0 skipped**, exit 0, 267.02 seconds. Native evidence: SQL overlap [3,3], six completed
cycles and six kernel retirement records; fixture rows one outcome, one paper
decision and one pending V2 plan. Status explicitly denies lifecycle authority.
Initial intermediate focused run: 150 passed; final source supersedes that run.
Full canonical: **1,950 passed, 17 skipped, 0 failed**, exit 0, 689.11 seconds.
Existing Discord/audioop deprecation warning only. Compilation and git diff --check
pass. Source fingerprints match the tested files. Original 29 pending files, CP77
witness and both protected RDB copies remain unchanged.

Nine unique synthetic databases were exported, fsynced and SHA256 verified before
fixture retirement. No database/container/volume was deleted. PostgreSQL smart
no-wait helper returned 0. Redis normal SHUTDOWN helper returned 137; this is NOT
silently normalized to success. Independent Docker state shows both isolated
servers exited 0/OOM false; their logs show normal requested shutdown. Redis helper
137 attribution remains UNKNOWN. No retry, forced stop or kill fallback occurred.

**Final preservation gate reconciled:** the user confirmed manually starting and
stopping Atlas on October 15, 2026, explicitly accounting for the observed
11:36:31/32 Chicago changes. This resolves the prior commit hold; it does not mean
Atlas's state was unchanged. No Atlas restart, modification or further investigation
was performed after that confirmation. The three original Genesis dependencies
retain their IDs, states and start times. Exact-owned fixtures retain their IDs,
images, ownership labels and isolated storage; both remain stopped with server
exit 0. All original pending and protected source/data fingerprints rechecked.

Read-only review of the Redis helper: retained command evidence records exit 137;
server logs independently show requested normal shutdown and server state is exit 0,
OOM false. The later bounded event query returned no retained events for that
window, so it cannot establish the helper's cause. Cause remains UNKNOWN. No retry,
force-stop, kill, delete or restart was issued to resolve it. A successful server
exit is not relabeled a successful helper exit or production durability proof.

Scoped implementation is certified for commit after explicit review of the five
files below. Overall GB-08 remains AMBER/HOLD for separate launch registries,
legacy writers, direct watchdog work and whole-supervisor lifecycle. Tests and
user-confirmed isolation do not grant a global write, snapshot or shutdown boundary.

## Full remaining roadmap and next priority

1. Deliver this certified inactive trusted-registry fence; Atlas discrepancy resolved
   by user confirmation, helper 137 cause preserved as UNKNOWN.
2. Authoritative cross-registry/process admission and complete actual supervisor
   worker inventory, including watchdog/health/file work and descendant identities.
3. Reproducible CP77 native witness packaging only with separate explicit permission.
4. Real-job interrupted recovery, complete child-to-Redis/SQL socket attribution,
   supervisor retirement/restart and independently authenticated acknowledgements.
5. Next/HMR safe integration remains blocked; no stock unsafe dev launcher.
6. GB-04 Gaming remains inactive; no measured performance/production claims.
7. Redis continuous durability and guarded migration prerequisites remain HOLD;
   inactive adapters only, preserved original migration edits and protected recovery.
8. Full Start/Stop/Restart/Gaming controls remain disabled until independently
   approved production lifecycle, recovery and exact-owned dependency certification.
9. Frozen V2 evidence adequacy/provenance reviews resume only when authorized;
   Intelligence Engine/Command Center, alerts/Discord and later product/security
   roadmap remain unchanged. No historical backfill, retuning or live authority.

Next recommendation: close the separate-registry and actual long-lived supervisor
boundary with a reviewed authority model, rather than presenting this process-local
observation as a global write fence. Do not expand authority as part of this patch.

## Exact scoped delivery files

- scripts/genesis_maintenance_observation.py
- scripts/genesis_maintenance_supervision.py
- tests/test_genesis_maintenance_fence.py
- tests/test_genesis_concurrent_maintenance.py
- docs/GENESIS_GB08_REPORT.md

AGENTS.md, CODEX-HANDOFF-LATEST.txt and the same canonical GENESIS FUTURE.txt are
local append-only continuity updates, not swept into the implementation commit.
Exact verified delivery SHA is recorded in those continuity files after push; no PR/main merge,
remote CI, signature or clean-worktree claim. Original 29 pending files remain.
