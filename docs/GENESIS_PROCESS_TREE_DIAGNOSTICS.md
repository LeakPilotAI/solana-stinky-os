# Genesis process-tree diagnostic contract

Checkpoint 59 investigated the missing process-tree difference from checkpoint 58.
The earlier abort did not retain the differing PIDs or ownership identities, so its
exact historical cause remains unknown. Do not label it harmless process churn.

`scripts/genesis_process_diagnostics.py` provides bounded, read-only snapshots.
It reuses the existing exact repository, runner, service and descendant validators.
Native image path, creation time and aliveness come from one held Windows process
handle. Stored commands are fingerprints, never raw arguments or credentials.

Compare every owned PID, parent, creation time, image path, role and command digest.
Report added, removed and changed identities explicitly. Equal process counts are
insufficient: PID reuse, changed ancestry, executable or command must fail closed.
Missing identities, malformed snapshots and ambiguous ownership also fail closed.
Unrelated system process counts may vary without changing the owned tree.
Offline comparisons retain historical differences; live unchanged-tree validation
additionally rejects acquisition-order contradictions and snapshots older than ten
seconds using the controller's monotonic clock. This is not a source-event timestamp.

These helpers do not suspend, terminate, start or resume processes. They do not
control Docker, Redis, volumes or experiment evidence. They do not replace the
existing ownership checks or certify collection health from a snapshot alone.

## Observed certification

An isolated Windows supervisor/child fixture reproduced genuine child churn:
two added child identities were recorded and the unchanged-tree gate rejected it.
Suspending and resuming that harmless fixture preserved all its native identities.
This establishes diagnostic behavior, not the cause of checkpoint 58.

One explicitly authorized production diagnostic pause used an independent resume
watchdog and held native identities. On October 9, 2026 UTC, the pause ran from
04:37:41.358595 through 04:37:41.870271 (about 0.512 seconds). All 32 owned nodes
matched before, during and after suspension. Global inventory counts differed;
the owned process tree did not. The 14 runner nodes are seven Windows virtualenv
wrapper/actual-interpreter chains, not 14 independent service supervisors.

The diagnostic performed no Redis/container/configuration mutation or migration.
Existing seven core supervisors remained unchanged, optional paper services stayed
absent, and independent HTTP, collection freshness, canonical V2 parity, immutable
hash and zero-authority checks passed. Atlas identities and start times stayed
unchanged. A short collection pause is not a claim of zero missing observations.

## Migration boundary remains blocked

The diagnostic did not reproduce the earlier mismatch. Incomplete capture, process
churn and an unexpected transient process remain hypotheses. A future migration
must capture exact fresh identities, reject any unexplained difference, establish
complete writer quiescence, prove a fresh recovery boundary and certify rollback
that preserves acknowledged post-cutover writes. Successful diagnostic suspension
alone is insufficient. Checkpoint 58's preparation stays uncommitted and its local
controller remains disabled; checkpoint 59 does not authorize a Redis cutover.

For any later diagnostic pause, require explicit authorization, independent safety
approval, exact owned handles, bounded duration, a tested resume watchdog and
independent post-resume health/evidence checks. Stop if approval rejects the pause.
