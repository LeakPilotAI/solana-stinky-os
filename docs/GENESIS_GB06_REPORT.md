# GB-06 recurring maintenance certification

October15,2026 America/Chicago. Base279d114215c5f69d6aeb0e4dc146fc84d41ade32,
branch chatgpt/443-intelligence-asof-dataset. Production integration remains inactive.
No Next dev launch or dependency patch. No production Genesis/Gaming startup.

## Scope and exact implementation

`scripts/genesis_maintenance_observation.py` gains an optional trusted retirement
verifier,defaultNone. A selected verifier must prove exact root PID,exit0,zeroactive
kernel descendants,verifiedidentity and the exact random jobID/sourceSHA256 before
owner claims are released. Encoded exact comparisons reject bool/integer ambiguity,
missing fields and stale/replayed proof. Parent authenticated launch challenge must
remain unchanged at completion and after retirement verification. A failure,HOLD,
missing child installation acknowledgement,nonzeroexit or changed generation keeps
HOLD and prevents silent replay. Callback evidence is a trusted integration seam,
not permission to supply arbitrary claimed truth. The native fixture supplies a
retained Windows kernel job/process-handle witness.

Existing production runner/schedules/retry code,all29pendingmodifications,CP77,
frozen policy/worker/schema sources and GB-04policy are unchanged. No manager or
retirement verifier is installed by default. Existing standalone default manager
root-exit behavior is not upgraded into full descendant certification by this opt-in
change. No live lifecycle authority or automatic production activation.

## Workload and dependency inventory

| Loop/entry | Existing cadence/retry | Dependencies/effects | Actual coverage |
|---|---|---|---|
| slow:post_migration.cli learn-success |21600s loop;normalhelper3attempts,15/30sbackoff|PostgreSQL outcomes,early-buyer attribution,wallet metrics|Native authenticated real CLI,nonempty isolated synthetic inputs,repeat,derived row checks,kernel retirement|
| slow:post_migration.cli recompute-performance |Same slowloop/helper|PostgreSQL wallet trades/performance|Native real CLI,one synthetic trade/wallet,repeat,derived count,kernel retirement|
| research:run_intelligence_shadow_scorer.py |60s loop;attempts1|Bounded calibration file,PostgreSQL tracks/snapshots/buyers,shadow-score insert|Native real script,fixture-only synthetic calibration and data,nonempty score insert,kernel retirement|
| research:run_intelligence_paper_decisions.py |60s loop;attempts1|PostgreSQL immutable scores -> paper decisions|Native real script,actual decision derived from fixture score,kernel retirement|
| research:run_intelligence_paper_execution_plans.py |60s loop;attempts1|PostgreSQL V3 ENTER -> V1plan|Native real script,V1plan insert from fixture decision,kernel retirement|
| v2:run_intelligence_execution_v2.py |10s independent loop;attempts1;passrecorder|Frozenregistry,decisions,plans,snapshots/results,read-only runtime-session provenance|Native unchanged real script,fixture registry policy and prospective admission,V2plan insert,kernel retirement;new plan remainsPENDING,no mature-outcome claim|
| research:watchdog_tick/recover_watch_dependencies |Same60sloop before research|Exact-owned3containerinspect/start under sharedlock|Existing behavioral tests with mockedDocker only;no live watchdog action or productionstart|
| research:dump_runtime |Same60sloop|HTTP probes,log state/ownership snapshots|Source-audited;full recurring native health/writer integration remainsHOLD|

Actual runner remains three concurrent loops,not one serialized schedule. Tests
invoke the exact real command entry modules/scripts sequentially to make fixture
assertions deterministic;they do NOT wait6hours,run the production supervisor loop
or claim simultaneous sustained cadence certification. Existing loop/admission
behavioral coverage is distinct from this native entry coverage.

## Isolated resource and evidence boundaries

A new exact-owned labelled `genesis-gb06-pg-*` container uses cached postgres16alpine
image,pinnedfullID/image/name,labelgenesis.certification=gb06,127.0.0.1:16606binding,
separate boundedtmpfs,/no productionbind/namedvolumes,512MiBmemory/1CPU limits.
Local test PostgreSQL trust authentication has no productioncredential reuse.
Test requires explicit GENESIS_GB06_PG_FIXTURE path and verifies fullDockerpin before
any DBaccess. Every run creates a uniquely named gb06_*testdatabase,neverdrops or
modifies a productiondatabase. Fixture setup and assertions use only fixed16606.
No production PostgreSQL,Redis,MinIO or Atlas dependency is started.

Real commands receive explicit fixture STINKY_DATABASE_URL and isolatedworkingdir,
not the production.env. Redis/RPC are unreachableloopbackport1guards;these SQLjobs
do not need a live Redis/marketprovider. WatchdogDocker is mocked,not invoked live.
The research calibration and boundary are explicit TESTargv/fixtures,not changed
productiondefaults or historical evidence. Immutable V2policy hashes/constants and
schema are reused unchanged against a new isolated synthetic registry. No real
runtime-session is fabricated. Synthetic DB facts are labelled fixture-only and
never inserted into production. No live-profitability/outcome claim.

The first successful native trial exercised8invocations:six distinct commands plus
learning/recomputation repeated. Database assertions required one tokenoutcome,
walletperformance,shadowscore,paperdecision,V1plan,V2plan;zeroV2results. Repeated
learning/recomputation retained one row per derived key. This proves actual input/
SQL/output paths for the bounded cohort,not exhaustive query/workload correctness.

## Ownership and descendant proof

Each command uses an authenticated maintain launch,explicit source-hashed manifest,
random per-job ID/private child key,existing30sprivate install/dispatch barrier and
fresh native PID/creation/image/command/ancestry checks. Native fixture uses base
interpreter plus explicit repo/venv importpaths to avoid a pre-job-assignment venv
wrapper race. Production executable/wrapper path is not changed or certified by
that choice;GB-03wrapper evidence remains separate.

Before dispatch,the retained CP77 `scripts/genesis_native_descendants.py` witness
assigns the exact fresh child to an unnamed Windows job with no breakaway or
kill-on-close policy. It retains creation-bound native handle;after normal exit,
activeprocesses0/rootexit0 and Popenexit0 are required. Descendants created after
assignment inherit membership. Jobhandleclose has no termination behavior.
No process was killed on failure/timeout. Private pipes carry secrets;no key is
placed in argv/env/status. Certification output contains only synthetic joboutput
and nonsecret kernel/evidence metadata.

Important reproducibility limit:that CP77kernel helper is preserved UNTRACKED work,
not swept into this commit. Native test explicitly importorskip when absent and
requires opt-in pinned fixture;do not claim clean-checkout native coverage or
productionbootstrap certification. The retirement interface/portable failures are
independently committed;the retained native fixture provenance is explicit.
No complete child-to-Redis attribution or global write boundary is inferred.

## Failure/retry/recovery coverage

Portable behavioral tests:correctproof,active descendants,wrongrootPID,wrongtyped
boolean,missingproof,verifierexception,nonzerochildexit,missingprivateack,staleparent
generation,replayedjobID,and invalidverifierconfiguration. Uncertain completion
keeps HOLD;new loop/job admission cannot silently retry or reopen the generation.
Only a new reviewed registration can recover;no automatic recovery routine added.

Native real-entry negative tests cover actual argparse rejection and an absent
isolated database on the same verified fixture endpoint. Nonzero exits must HOLD
before retirement callback and count only one admission,not completion/retry.
These are not native crash/networkpartition/timeout fault injections. Existing
GB-03/GB-05Abehavioral tests cover duplicate/stale/replay/timeout primitives;no new
claim that a crashed SQL transaction or partially acknowledged real job is safe to
replay. Real interrupted-business-work recovery remainsHOLD.

Ordinary production retryhelper/cadences are unchanged. In explicitly authenticated
mode,uncertain job completion intentionally raises before automaticretry;this was
already managerHOLD behavior. Tests do not change underlying SQL/research semantics
or weaken retries to hide failures. All Gaming criticalroles/maintenance loops
remainprotected and policyinactive.

## Remaining roadmap / limitations

1. Certify full actual maintain-supervisor bootstrap,concurrent sustained3loop
   cadence,pass/health/dump_runtime ownership,in-flight job protocol and graceful
   retirement of the long-lived supervisor. Entry completion is not supervisorstop.
2. Certify native crash/timeout/partialtransaction/reply ambiguity against real
   workload with safe no-kill fixtures;keep replayHOLDuntil per-job reconciliation.
3. Reconcile/commit CP77kernel witness separately if authorized;then clean-checkout
   native packaging and production-wrapper/bootstrap proof can be established.
4. Nextdev remainsGB05Bblocked:publiccustomserverretainsforcednestedworkers;
   upstream/version-pinnedintegrationreview needed before realNextlaunch.
5. Child-ownedRedisfactory/syncasyncpooldirectreconnect/native socketclosure remains
   HOLD;no productionadapteractivation or durableRedis/lifecycleclaim.
6. GB04performancebudgetsproposed/unmeasured;no Gamingactivation/throttling ofthese
   maintenancejobs. SavedfinalACKboundary,PG/MinIO/frozenevidencerecovery,fullowned
   cooperativeStop/snapshotrestore/desktopWindowslifecycle need separatecertification.
7. Preserve allV2/provenance/clockcontradictions/runtime/provider/#439/Intelligence
   Engine/CommandCenter/product/Discord/SaaS/account/entitlement/audit/security
   roadmap. Start/Stop/Restart/Gamingdisabled;noCP78/livecapital/signing/wallets/orders.

Final measuredtests/container/saved-statechecks and verifiedcommit/pushidentity
are recorded after certification below and in append-only canonical continuity.

## Final certification and resource reconciliation

- Focused/native/watchdog/supervisor/Gaming: **99passed,0failed,0skipped**,exit0,
  202.04seconds. Fullcanonical: **1,895passed,17skipped,0failed**,exit0,662.77seconds.
  Existing Discord/audioopwarning. Exact text/XML under ignoredlogs/gb06.
- Initial bounded six-entry native trial1passed in99.92seconds;expanded final
  results supersede that narrower trial. No unavailable Ruff/mypy/remoteCI claim.
- New Python compilation and diff checksPASS. FrozenV2worker,policyfreeze and
  registry/evidencemigrations matchHEAD. All29originalpendingtrackedbytes and both
  protected RDBSHA256 unchanged. ExistingCP77/untrackedwork not staged/discarded.
- Exactly3new isolated synthetic test databases were exported via pg_dump to unique
  ignoredlogs/gb06/gb06_*.sql,fsynced and SHA256verified before normalPGshutdown.
  Exports are retained test artifacts,NOT independently restore-certified production
  snapshots. No existing database/container/volume/data was removed or overwritten.
- PGfixture smartshutdown helper dockerexec returned137. No retry/escalation.
  Independent pinnedcontainerstate:exited,exit0,OOMKilledfalse;boundedserverlog
  confirms receivedsmartshutdownrequest,completedshutdowncheckpoint and systemshutdown.
  Thus normalserverclosure is verified despite failedhelperstatus. Exact helper
  termination cause is not independently established;do not equate137withserverdata
  loss or claimhelperexit0. The discrepancy is retained in final-resources.json.
- Redisfixture verifiedempty/onlyinspectionclient then normalredis-cliSHUTDOWN;
  serverexited0. No dockerstop/killfallback. Both exactownedtestcontainers retained
  stopped. PGtmpfs test contents are exported;no productionnamedstorage shared.
- Original5Genesis/AtlascontainerIDs/states/starttimesmatchbaseline. No production
  dependency/applicationstart,Atlasaction,Nextlaunch or market/DBcounterclaim.

Finalscope:scripts/genesis_maintenance_observation.py,
tests/test_genesis_recurring_maintenance.py,docs/GENESIS_GB06_REPORT.md.
AGENTS,masterroadmap,handoffupdatedappend-onlyoutsideimplementationcommit;GitHubSHA
recordedthereafterverification. Indexreviewexcludesall29originalpendingfiles;
trackedworktreeintentionallyretainsCP77/migrationchanges,notclaimedclean.

Verdict: scoped inactive verifier and bounded real-command fixture certified;
**overall GB-06 AMBER**,because full recurring-supervisor/concurrency/cadence,
real interrupted-work reconciliation,independent helper/grandchild authentication,
clean-checkout native fixture packaging and production ownership remainHOLD.
Kernel job membership proves retirement,not individual authentication of every
transient PowerShellhelper or a Rediswriteboundary. No broadened lifecycleauthority.
