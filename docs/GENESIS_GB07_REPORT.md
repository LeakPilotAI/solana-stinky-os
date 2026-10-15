# GB-07 concurrent maintenance and SQL recovery

October15,2026 America/Chicago. Base1f18a2965d252ad885b23d9b6e79845b6ed73ce2,
branch chatgpt/443-intelligence-asof-dataset. Inactive isolated engineering only.
**Overall AMBER; complete actual supervisor ownership/retirement remains HOLD.**

## Actual bootstrap map and safe harness boundary

Existing `scripts/run_genesis_service.py` main maintain path starts slow-maintenance
and V2 in separate threads;research/watchdog/health runs on the main thread. All use
existing supervisor_loop,supervisor_running,supervisor_wait and run_job_with_retry.
Private observation bootstrap and source-hashed MaintenanceObservation route job
admission;this milestone does not replace the runner,which is one of29preserved
pending files. No production supervisor or installed Next launcher is executed.

| Loop | Production cadence and entries | Concurrent native wave coverage |
|---|---|---|
| v2-maintenance |10seconds;frozenV2worker;attempts1;pass recorder|Actual unchanged worker,private authenticated child,kernel exit witness|
| research-maintenance |60seconds;watchdog/dump_runtime;shadow scorer -> paper decisions -> V1plans;attempts1|Actual paper-decision entry concurrently with other loops;full research chain separately GB-06;watchdog mocked tests|
| slow-maintenance |21600seconds;learn-success -> recompute-performance;normal retry helper|Actual learn-success entry concurrently with other loops;recomputation separately GB-06|

Harness owns3threads and invokes representative real command entry points rather
than running the desktop main loop. Two waves use an injected logical scheduling
clock0->21600,without waiting6hours. PERIODS remains10/60/21600. SQL/evidence clocks
remain real PostgreSQLUTC;frozen admission/maturity rules are never time-warped or
extended. This is not complete6command cycles or sustained production cadence proof.
V2 eligibility may legitimately expire during tests;no timestamp backdating or
expectation weakening is permitted to force an admission.

## Inactive admission/drain implementation

New `scripts/genesis_maintenance_supervision.py` contains MaintenanceDrain and a
bounded transaction-outcome classifier. No executor,spawn,signals,process killing,
production importer,env activation,controlpanel hook or automatic startup.

Explicit isolated=True and typed manager with retirement verifier are required for
admission. Fresh authenticated parent challenge is pinned;generation replacement
or managerHOLD blocks admissions. One active cycle per known loop,maximum3distinct
loops;unknown/Atlas roles and overlap latchHOLD. No queue or background scheduler.
Completed counters represent registered cycles,not individual SQL commits or V2
powered sessions. Actual jobcompletion/retirement remains the GB-06manager gate.

Generation claims are bounded64perLaunchObservations controller,process-local and
weakly held. A duplicate/new drain object cannot reopen the same authenticated
generation,including after quiescence. Fresh private parent reauthorization is
required for another generation. This is not a durable multi-process broker or
proof against a different external controller;production authority remains HOLD.

request_drain fences new cycles and issues a private signed request bound to parent
session/generation and a fresh nonce. drain validates it,waits on a condition for
active cycles without cancelling jobs,then requires manager loops/owners empty and
an independent idle verifier. Timeout,missing/replayed reply,clock regression,
parentreplacement,unresolved work or idleproof mismatchHOLD. Successful status is
QUIESCED_OBSERVATION,explicitly **not supervisor-process exit**. No retired native
supervisor process is inferred from stopped fixture threads.
The underlying MaintenanceObservation remains a separate trusted object:direct
admissions outside this controller are not globally fenced by MaintenanceDrain.
Such bypass/unknown-writer paths must be closed and independently inventoried before
claiming a final write/snapshot boundary. This controller's quiescence statement is
strictly for its registered cycles;it cannot grant global shutdown authority.

## Concurrent native evidence and observer repair

Exact-owned retained PostgreSQLfixture127.0.0.1:16606 and Redisfixture16603 were
reused,after pin/name/image/label/loopback/storage checks and previous GB-06SQLexport
hash verification. Storage is separatetmpfs,no production binds/namedvolumes. Each
trial creates unique gb07_*databases;no original data is overwritten/dropped.
Redis is PING/readiness only;no production Redis clients/credentials/persistence
changes or complete Redis ownership certification. Test-storage census44%used before
canonical;no capacity increase,expiry or cleanup used to obtain passing results.

Each job has its own source-pinned command,private jobkey/ID,30second auth/dispatch
barrier and actual native PID/creation/image/command/parent evidence. A test-only
barrier releases all3authenticated entries together. An isolated SQL table lock
holds their real requests;bounded watcher must independently see >=3waiting
backends before releasing the lock. The lock is rolled back cooperatively even
on failures. No OS/backend termination or actual dependency outage is injected.

Initial trial failed overlap:all3jobs exited0 but observer maximum0. A separate
2connection diagnostic proved PostgreSQLtransaction-cached activity statistics:
firstsnapshot0,newconnection then still0,explicitpg_stat_clear_snapshot then1.
Watcher now refreshes only its stats snapshot;the >=3overlap assertion and30second
private deadlines remain unchanged. Dedicated regression preserves this finding.
First corrected trial measured **[3,3]simultaneouswaitingSQLsessions**,6registered
cycles completed,emptyactivecycles,QUIESCED_OBSERVATION,and fixture counts1outcome,
1paperdecision,1V2plan. No production/profitability/session-adequacy inference.
Final focused/canonical trials independently repeat these assertions.

## Descendant authentication versus kernel closure

Each direct application job has its own authenticated child bootstrap;no inherited
parent key is accepted as that job's identity. The preserved CP77 Windows witness
attaches the exact fresh root before dispatch and retains a creation-bound handle,
requiring rootexit0 and zeroactive kernel descendants before ownership release.
Normal process exit only,no kill-on-close/breakaway configuration or forced cleanup.

Kernel membership proves containment/retirement;it does **not** independently
private-authenticate every transient helper. PowerShell native-inspection helpers,
all possible application-created grandchildren and the long-lived supervisor's own
private bootstrap/exit are NOT individually certified by this harness. No complete
supervisorGREEN or production lifecycle authority. Real native supervisor restart,
crash and graceful whole-process retirement remain HOLD. Generation replacement,
restart claims,overlap,timeout and lostack are behavioral fixture tests,not falsely
reported as native crash/restart certification.

## Cooperative SQL interruption/recovery

A separate isolated database runs a declared atomic operation with operationID and
SHA256marker in the same transaction as its effect. Independent connection cannot
see an in-flight marker:classificationAMBIGUOUS. Cooperative exception beforecommit
rolls back via asyncpg transaction context;confirmed rollback plus writer closure
and absent marker classifyROLLED_BACK. Cooperative exception aftercommit simulates
lost jobreply;independent matching marker provesCOMMITTEDfor **that transaction**.
Committed effect count remains1;no automatic replay. Contradictory rollback/commit
claims,mismatched hashes,unclosed writers or absence without rollback proof remain
AMBIGUOUS. Malformed IDs/hashes/booleans rejected. Marker observation is scoped to one
declared atomic transaction,not proof the full real maintenance job completed.

No frozen worker,productiontransaction,backendkill,pg_terminate_backend,network reset
or historical backfill. Interrupted multi-transaction real jobs remainHOLD pending
per-job reconciliation;the classifier has no execution/replay API.

## PostgreSQL helper137 investigation

GB-06original report/final-resources.json retain smartshutdown helper137,serverexit0,
OOMfalse and normalshutdown log. No evidence overwritten or failure relabelled.
Read-only pg_ctl--help confirms -w(default) waits for completion,-W does not wait,
smart quits after clients disconnect. After all tests,exports and clean client
closure,a smart-W request will be compared with independent server exit/log proof.
No timeout escalation/kill fallback. A return0 would support,but not by itself prove,
the hypothesis that the old waitingexec helper outlived PID1/container namespace.
Exact helper termination cause remainsUNKNOWN without lower-level evidence.

## CP77 witness audit and packaging proposal (NOT executed)

Preserved untracked `scripts/genesis_native_descendants.py` SHA256: 3cee9d3c14027e0425ca94ea857e3769011342bb81aa5c86d67bcf426020a6ab.
Source inspected:exactnativeidentity before/after assignment,retainedcreationticks,
unnamedjob/defaultflags,no SetInformationJobObject kill-on-close/breakaway setup,
GetProcessTimes/GetExitCodeProcess/QueryInformationJobObject membership proof.
AssignProcessToJobObject requires TERMINATEaccess rights;the helper exposes no
termination call. Closing handles does not kill retained failed children.
AllCP77files remain unstaged/unmodified. Testsimportorskip if witness absent;
therefore native reproducibility on a clean checkout remainsHOLD.

Proposed separate explicitly authorized packaging checkpoint:
1. Review exactly this captured witness version and bounded native tests;do not
   sweep otherCP77/migrationfiles into a commit or rename/copy it to evade protection.
2. Stage only the explicitly approved witness plus narrowly scoped new tests,
   preserving its content and all unrelatedpendingwork. No authorization inferred.
3. Test retained-handlePIDreuse,unknown descendants,orphanexit,job-assignmentfailure,
   >64memberbound,nonzeroexit,no-kill-on-close behavior,missingnativeAPI and cleanup
   under a clean Windows checkout. Never kill a process to make tests pass.
4. Verify packaged imports and sourcehash,repeat nativefixture in cleanindex/checkout,
   document Windows/version limits. Packaging grants no lifecycle authority or
   automatic startup;full descendant authentication remains a separate gap.

## Preservation / remaining roadmap

All29pendingtrackedfiles,fourmigrationedits,CP77 and saved-state copies remain
unchanged. GB04Gamingpolicyinactive;criticalmaintenance/collection/alerts/persistence
not throttled. Sourcecadences,frozenworker/policy/evidencemigrations and research
boundaries unchanged. Atlas read-only baseline/final identity comparison only.
No productionGenesis/Next/Gamingstart,dependencyrestart,livecapital,signing,wallets,
orders,autostart,VPS,globalresourcecontrols,Dockerprune or container/volumedeletion.
Start/Stop/Restart/Gamingdisabled;Redisdurability,completechild-to-Redis and full
productioncooperativeshutdownHOLD.

Exact final test counts,resource teardown and verifiedcommit/pushidentity recorded
below and in append-only AGENTS/masterroadmap/handoff. Remaining priorities:
1. Full actual supervisor bootstrap/safe log/watchdog redirection;allcommandsperloop,
   native whole-supervisor restart/drain/exit and individual helper/grandchild auth.
2. Per-real-job multi-transaction interruption/partialack recovery without replay of
   ambiguity;controlleddependencyoutage tests beyond existingrejection/mocks.
3. Separately authorized CP77witnesspackaging/cleancheckoutcertification per plan.
4. NextGB05B supported/upstream version-pinned integration review;no unsafe devlaunch.
5. ChildRedisfactory/pool/direct/async/reconnect/native socket provenance and authority.
6. GB04measuredresource/criticalqualitygates;savedfinalACKboundary,PG/MinIO/frozen
   evidence recovery,completeowneddesktop/Windowslifecycle afterseparatecertification.
7. PreserveallV2/provenance/clockcontradictions/runtime/provider/#439/Intelligence
   Engine/CommandCenter/product/Discord/SaaS/account/entitlement/audit/security
   roadmap. No CP78/backfill or production-readiness claim.

## Final certification and delivery

- Focused/native/GB06/watchdog/supervisor/Gaming: **125passed,0failed,0skipped**,
  exit0,256.07seconds. Fullcanonical: **1,921passed,17skipped,0failed**,exit0,
  711.20seconds. Existing Discord/audioopwarning. Exact XML/text in ignoredlogs/gb07.
- Initial observer trial18passed/1failed retained;corrected narrower trial20passed
  in53.13seconds. Final expanded results supersede earlier trial counts. No assertion
  weakened,deadline increased or failing nativecase excluded. Pythoncompile/diffPASS.
- Ten synthetic fixture databases exported to unique SQLfiles,fsynced/SHA256verified
  before shutdown. Artifacts retained;not independently restore-certified production
  backups. No database dropped and no prior export/protected snapshot overwritten.
- Smart no-wait pg_ctl helperexit0;independent serverexit0/OOMfalse and log confirms
  smart request,shutdowncheckpoint and systemshutdown. Redis normal SHUTDOWN after
  verifiedempty/onlyinspectionclient,serverexit0. No forcedstopfallback. Both exact
  owned testcontainers retained stopped. Historicaleventwindow returned no retained
  events;old137cause remainsUNKNOWN. New0vsold137supports namespace/wait hypothesis
  but does not establish a causal proof. Original GB06evidence preserved.
- Original5Genesis/AtlascontainerIDs/states/starttimesunchanged. All29pendingtracked
  bytes,fourmigrationedits,CP77witnessSHA256 and protectedRDBcopies unchanged. Frozen
  worker/policy/research source unchanged. No fresh productionDB/counter/capture claim.
- Exact3files:scripts/genesis_maintenance_supervision.py,
  tests/test_genesis_concurrent_maintenance.py,docs/GENESIS_GB07_REPORT.md.
  NoCP77file staged/overwritten/committed. AGENTS,canonicalmasterroadmap and handoff
  appended after remote verification;SHA recordedthere. NoPR/mainmerge/remoteCI,
  unavailableRuff/mypy or clean-worktree claim. Original29pendingfiles remainlocal.

**Verdict: scoped inactive controller and representative concurrent fixtures
certified;overallGB07AMBER.** Full commandsperactualsupervisorloop,privatebootstrap,
individual helperauth,native whole-supervisor restart/exit,globalmanager/bypass
fencing,multi-process authority and interruptedreal-job recovery remainHOLD.
PGbackendcounts are fixture-local aggregate concurrency evidence,not a complete
Windowschild-to-PGsocketjoin. No production lifecycle or Redis authority granted.
Nextpriority is to close direct/unknown admission paths and independently prove the
actual supervisor boundary before using quiescence as a snapshot/write fence.
