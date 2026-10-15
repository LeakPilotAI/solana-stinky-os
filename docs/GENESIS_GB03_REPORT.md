# GB-03 — authenticated wrappers, Node and maintenance

October 15, 2026 America/Chicago. Base
`9cf30b0a29a093dfee8d02e066a8dab0413f04b8`, branch
`chatgpt/443-intelligence-asof-dataset`. Default-off isolated integration.
Production ownership remains AMBER. No lifecycle controls enabled.

## Architecture and actual coverage

| Path | Evidence added | Boundary still HOLD |
|---|---|---|
| Windows Python venv launcher → base interpreter | Real native wrapper/interpreter, private challenge to actual leaf, exact ancestry/image/argv/creation pins, signed dispatch-ready | Other wrapper shapes or unpinned descendants |
| Direct Python service entry | Prior protocol retained; optional authenticated lineage | Real seven-service DB/source workloads |
| Node private entry | Native Windows Node, real HTTP/listener ownership and post-bootstrap stdin delivery | Lifetime ownership between snapshots and future unregistered forks |
| Node → Next production custom server | Explicit isolated real Next build, existing CP77 stdin bootstrap, HTTP request/drain, kernel descendant exit proof | Supplemental working-tree CP77 fixture; not clean-checkout production certification |
| Desktop Next development/HMR chain | Inspected `node next/dist/bin/next dev -p 3000 -H 127.0.0.1`; npm fallback remains separate | **HOLD**: Next-created workers/HMR descendants lack this private generation protocol; never implicitly authorize them |
| slow-maintenance | Native authenticated synthetic job and actual runner loop-admission hook | Real learn-success/recompute-performance workload |
| v2-maintenance | Native job entry plus unchanged real frozen-worker CLI `--help` via venv; immutable source pin and blocked database URL | No experiment/database/business-workload execution |
| research-maintenance | Native private job entry and three-loop thread-local concurrency | Real research/scoring/planning workload and watchdog activation |

Native HTTP tests use isolated ephemeral loopback ports. Production port3000 is
not claimed certified. Existing listener-verification code covers the observed PID,
native descriptor and socket; unknown descendant tests explicitly return HOLD.
There is no change to production web mode, ports or application data.

Seven-service position (all production integration remains inactive):

| Service | Certified isolated path | Remaining live/workload gap |
|---|---|---|
| event-log | Existing direct Python bootstrap regressions | ASGI/database publication and native writer join |
| api | Existing direct Python bootstrap regressions | Actual API/background queues and writer join |
| sentinel | Existing direct Python bootstrap regressions | Source/watch/outbox/BRPOP workers |
| collector | Existing direct Python bootstrap regressions | Actual tracks/database/observation workers |
| entities | Direct Python plus new native venv pair | Resolution/funding/reconciliation workload |
| web | Native Node/socket plus isolated production Next/CP77 join | Development CLI/HMR/forked workers and production authority |
| maintain | Three-loop admission, native jobs and actual frozen CLI help | Real recurring/frozen business workloads, full descendant exit and writer accounting |

## Wrapper protocol

WrapperObservation accepts a trusted set of absolute executable pins and the exact
spawn command. It independently captures a bounded root-to-leaf chain (maximum4),
matches every native image and command, requires stable before/after descriptors,
and rejects duplicates, missing roots, foreign ancestry and unexpected descendants.
Each descriptor binds PID, parent, creation time, image and command SHA256. Windows
path normalization permits case differences without substring matching.

The private challenge now optionally includes the exact lineage. The child checks
every native member itself; the controller repeatedly checks both lineage and
supervisor generation. A copied public record or a heartbeat cannot substitute for
fresh private authentication. Existing direct-parent frames remain compatible.
The deadline is still30seconds, including dispatch-ready and final wrapper audit.
Missing/failed evidence HOLDs without process termination. Observations do not
prove historical absence of transient processes or grant lifecycle authority.

A short-lived venv job independently reproduced a second ordering gap: it exited0
before the final closed-tree audit, correctly causing HOLD at DISPATCH_READY.
Children now remain at the signed dispatch-ready barrier until the parent completes
that audit and the supervisor's native callback, then sends a signed
observation-complete continuation. This keeps the
existing receipt and30sdeadline; it does not skip verification because a worker
exited successfully. Timeout status cannot later flip from HOLD to OBSERVED when
a delayed pipe write finishes. Late-write and failed-final-audit tests cover this.
Both inactive helper ends must be deployed together; no production rollout occurs.

An expanded trial subsequently hit the same unchanged30sdeadline because repeated
individual PowerShell queries multiplied wrapper checks. Each phase now uses one
fresh bounded before/after batch of its required PIDs (maximum6); no batch is reused
across phases. PID sets must be complete, unique and identical on both reads, and
all image/command/creation pins still match. Missing, foreign, duplicate and reused
PID batch tests fail closed. Separate full descendant censuses remain in place.

## Node and CP77 compatibility

The Node adapter pins the exact absolute Node image and target command. It reuses
the Python controller's private-child phases and signed dispatch-ready protocol.
Its receiver reads exact bounded stdin lines synchronously before dispatch, leaving
later CP77 stdin untouched. Keys never enter argv, environment, status or logs.

Python canonical challenge bytes, including exact nanosecond integers, are signed
without unsafe JavaScript Number reserialization. Node verifies receipt MACs,
targets, native parent/owner identity and a conservative local deadline. Invalid
proofs, altered receipts, duplicates and timeouts do not dispatch the target.
Native tests use a marker to prove denied targets never ran.

The preserved CP77 production-mode custom server was tested through the new Node
entry without modifying its untracked source. Its independent fixture lifecycle
capabilities are not observation keys and never activate production controls.
The supplemental test requires explicit opt-in and the preserved CP77 fixture;
ordinary canonical runs skip it. It is run separately in focused certification.
Default SupervisorObservation still rejects mixing cooperative and observational
controllers. Stdin interoperability does not certify that higher-level coupling.

Actual Next dev/HMR spawns are not silently accepted: the generic closed-tree
audit rejects a real unexpected Node child. The dev CLI/npx/npm wrappers need
separate private child delivery and active-HMR certification before authorization.

## Maintenance admission and scheduling preservation

The supported runner's existing three loop decorators can enter an explicitly
installed MaintenanceObservation. Existing retry attempts, sleep intervals,
watchdog, research boundaries, arguments and frozen-worker code are unchanged.
No manager is installed by default or by environment/CLI switches.
In explicitly observed trials, nonzero/unresolved job completion instead latches
HOLD and blocks re-admission; it is not permission to replay a potentially mutating
job. This fail-closed mode is not activated in the production retry path.

Each loop uses thread-local admission. A trusted manifest lists exact commands and
source files; the inactive manager verifies source hashes before admission, and
the private child verifies source/target again before dispatch-ready. Source reads
are bounded4MiB. Unknown commands, wrong loops, duplicate admissions, changed source,
overlapping owner claims or unresolved completion latch HOLD. At most3loop slots
and64trial admissions are supported; this is not indefinite production capacity.
Root exit is checked but is explicitly not proof of all descendant exit or Redis
drain. Failed channels may retain unresolved children; no forceful cleanup follows.

Read-only actual job map:

- slow-maintenance: `post_migration.cli learn-success`, then
  `post_migration.cli recompute-performance`; unchanged21600s wait.
- v2-maintenance: `scripts/run_intelligence_execution_v2.py`, attempts1;
  unchanged10s wait and pass recorder.
- research-maintenance: unchanged watchdog and
  `run_intelligence_shadow_scorer.py` / `run_intelligence_paper_decisions.py`
  with boundary `2026-10-05T12:46:27.418241+00:00`, limit500; then
  `run_intelligence_paper_execution_plans.py` with boundary
  `2026-10-07T07:09:02.404079+00:00`, limit500; unchanged60s wait.

Tests execute harmless isolated scripts, not frozen/research business workloads.
The unchanged V2 worker is additionally bootstrapped with `--help` only, with an
invalid database URL guard, and source bytes compared before/after. Argparse exits
before connection/experiment logic. Script-mode dispatch restores the script's
directory on sys.path, matching ordinary Python script execution and its sibling
imports; no frozen source is patched to accommodate the bootstrap.
Actual runner decorator tests exercise all three concurrent loop contexts with
explicitly mocked native owners. Native job tests separately verify OS processes.
These distinct proofs are not combined into a claim of full live maintenance health.

## Preservation, tests and safety

All29pre-existing tracked modifications were fingerprinted before work. The four
migration files remain byte-identical. The runner contains only new additive hooks
over the preserved working contents; the commit stages those hooks against HEAD,
excluding pending CP77 changes. All other CP77/untracked work remains intact.
No reset, stash, clean, Docker cleanup or broad process termination.

An initial native trial caught a Python local-name collision in the new job branch:
`target` shadowed the receipt hashing helper. It was renamed `job_target`; failed
trials remain in logs. Neither authentication assertions nor deadlines were relaxed.
The independent harness also needed its exported runner import path corrected;
that diagnostic-only issue was not an application defect.

The first canonical trial passed1,799tests/17skips before the additional short-job
case exposed the audit race. Those intermediate counts are not the final expanded
certification; final counts below include the new barrier/CLI regressions.

The only Docker control is the exact previously empty isolated Redis test fixture
for existing authentication/recovery regressions. No production dependency or Atlas
container is started, stopped, reconfigured or replaced. Saved-state hashes and
frozen V2 source are independently checked. No fresh DB-counter/evidence claim is
made with production dependencies stopped. No live trading, production credential
changes, transaction signing, wallet operations, orders, automatic startup, VPS or
gaming changes.

Final measured test counts and commit SHA are recorded after certification below
and in the canonical roadmap/handoff. Full Redis durability and cooperative shutdown
remain HOLD; Start/Stop/Restart/Gaming controls remain disabled.

## Remaining roadmap

1. Authenticate actual Next dev/HMR/nested workers and npm fallback, with closed-tree
   socket/identity evidence; no implicit worker exemptions.
2. Provision the trusted real maintenance command manifest, certify frozen worker
   bootstrap/real workloads, descendant exit and concurrent active-job failure cases.
   Extend bounded trial retirement only with evidence, not by lifting limits.
3. Couple observation and CP77 capabilities explicitly; complete child-owned Redis
   factory provisioning, reconnect/generation rotation and full native socket joins.
4. Reconcile final acknowledged saved-state boundary and PG/MinIO/frozen evidence
   recovery before separately authorized manual startup or lifecycle controls.
5. Full cooperative drain, independently restored final snapshot and exact owned
   dependency/desktop/Windows lifecycle remain separate live-approval milestones.
6. Preserve the full V2/provenance/runtime/provider/#439/Intelligence Engine/Command
   Center/product/Discord/SaaS/account/security roadmap. No CP78 or live authority.

## Certification environment clarification

A final restricted-sandbox canonical attempt stalled before the first CP77 async
test body. A separate single-test diagnostic with faulthandler identified Python
3.12 asyncio ProactorEventLoop initialization blocked in socket._fallback_socketpair
accept. Both diagnostic test sessions were interrupted through their exact handles.
No application process was targeted. The unchanged canonical suite was rerun with
approved local socket access; no test exclusions, assertions or runtime checks were
changed to handle this environment limitation. The earlier interrupted run has no
pass/fail completion claim.

## Final certification

Focused/native: **49 passed, 0 failed, 0 skipped**, exit 0, 246.60 seconds.
This used the independently exported staged runner and the explicit isolated
Next/CP77 fixture. Canonical: **1,809 passed, 17 skipped, 0 failed**, exit 0,
433.64 seconds. One existing discord/audioop deprecation warning. JUnit and text
results retained under ignored logs/gb03-canonical-network.*. No unavailable
Ruff/mypy or remote CI check is claimed. Exact staged Python compilation, Node
syntax and working/staged diff whitespace checks pass.

Five original Genesis/Atlas container IDs, states and start times exactly match
the recorded baseline. The one exact owned isolated tmpfs Redis fixture had zero
keys and only the inspection connection after tests; it was stopped and retained,
never deleted. No production dependency or Atlas operation occurred.
Both protected RDB copies remain 6,374,548 bytes with SHA256
658276641112471b58814233a3239f2d2b2413982a7fbf6bda4c1e184deaddfe.
This preserves earlier recovery evidence, not a new final acknowledged boundary.

All 28 other pre-existing tracked file fingerprints remain unchanged. Only the
three narrow runner hooks are staged; the original CP77 runner diff remains local.
The four original pending migration edits are excluded. Existing untracked files,
data and saved-state artifacts are preserved. Working tree intentionally retains
pending CP77/migration work, so no clean-worktree claim is made.

### Exact committed scope

- `docs/GENESIS_GB03_REPORT.md`
- `docs/GENESIS_PRIVATE_CHILD_REGISTRATION_REPORT.md`
- `scripts/genesis_child_observation.py`
- `scripts/genesis_maintenance_observation.py`
- `scripts/genesis_node_observation.py`
- `scripts/genesis_private_child_channel.py`
- `scripts/genesis_private_child_entry.py`
- `scripts/genesis_private_node_entry.cjs`
- `scripts/genesis_supervisor_observation.py`
- `scripts/genesis_wrapper_observation.py`
- `scripts/run_genesis_service.py`
- `tests/test_genesis_gb03.py`
- `tests/test_genesis_private_child_channel.py`

Commit and push identity is recorded in the canonical roadmap and handoff after
GitHub verification. No main merge, signature, PR or remote CI claim is made.
Isolated mechanisms are certified within the coverage matrix; **production
ownership remains AMBER**, full shutdown and Redis continuous durability HOLD.
The next safe milestone is isolated Next dev/HMR descendant provenance followed
by real maintenance command/worker coverage and child-owned Redis/socket joins.
No production lifecycle or startup authorization is granted by this checkpoint.
