# Core startup and separate paper-service audit

The seven checkpoint 41 core services are event-log, API, Sentinel, collector,
entities, frontend and maintenance. Maintenance runs the existing independent V2
loop (single attempt, 10-second sleep), plus unchanged scorer/decision/V1 research
and slow maintenance. Frozen V2 reads `intelligence_paper_decisions`, shadow scores,
migration tracks and snapshots; its session identity is the collector supervisor.
It imports ownership helper functions from `start_paper_runtime.py`, but this does
not launch or require either persistent paper service. Source inspection and actual
forward V2 evidence while both services were absent establish that dependency split.

| Service | Inputs and startup requirements | Durable effects | Core/V2 dependency |
|---|---|---|---|
| paper-intake-producer | Existing API environment/database/tables; loads registry-authoritative active policy, clears stale policy environment if absent; 2-second loop | Creates producer epoch if missing; freezes eligible alert-candidate cohort records after the recorded epoch, pattern occurrences and conditional policy-bound intake bundles; attaches valid recorded outcomes; enqueues due closes | Separate prospective paper cohort/intake workflow; not V2 admission/result production |
| paper-runtime | Existing database and caller-persisted intake bundles; 2-second idle poll | Locks one unprocessed intake with FOR UPDATE SKIP LOCKED; validates hashes/policy identity; creates immutable paper result and marks intake processed atomically | Separate persistent shadow/paper bundle processing; not frozen V2 worker |

Starting these services is not passive monitoring. They can create/update separate
paper state and add database workload, even though authority remains paper-only.
The producer can freeze candidates/attach outcomes without an active paper policy;
missing active policy prevents configured paper bundles, not every producer write.
The worker can process already-persisted bundles independently of current policy
activation. Existing unique candidate/intake IDs and conflict guards protect durable
identity; worker transaction locking protects concurrent intake processing. These
protections do not justify duplicate supervisors or guarantee zero duplicate query
work, so launcher native ownership/serialization still applies.

Bounded read-only live audit at checkpoint 44 found no active paper policy and zero
pending intakes in a 100-row capped sample (101st-row truncation probe). Recorded
producer epoch remains 2026-09-10T06:29:37.125216+00:00. Both services were absent;
none was started for this audit. Their historical separate cohort remains preserved.
A future explicit full start can catch up on eligible existing post-epoch separate
paper work; that is not a frozen V2 backfill and is not performed in this checkpoint.
No policy is provisioned or activated by selecting a startup profile.

Core-only startup preserves the user's currently running collection/Intelligence
V2 functionality. It does not promise ongoing separate paper-intake/result research.
Use explicit `--full` / `--full-startup` for that separate workflow. Core-only does
not stop already-running paper services or erase their startup metadata. The same
ownership, read-only dependency/schema checks and serialized recovery govern both
profiles. No frontend/API contract, frozen V2 policy, migration, worker, evidence,
threshold, signing, wallet, order or live trading permission changes.
