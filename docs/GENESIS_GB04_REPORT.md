# GB-04: inactive Gaming Optimization foundation

October 15, 2026 America/Chicago. Base `9e6171ef3938f79cd2de48cbcd19d2aa6473d776`,
branch `chatgpt/443-intelligence-asof-dataset`. No production startup or activation.

## Resource inventory and dependency classification

This is a source/dependency inventory, **not measured running-service utilization**.
Production Genesis is not started for profiling. CPU, memory, GPU, disk, network
and latency measurements are unavailable; zero usage must not be inferred.

| Service | CPU/memory sources | Disk/network dependencies | Classification and policy |
|---|---|---|---|
| event-log | ASGI request serialization, transport buffers, Redis reconnect | HTTP ingestion, Redis stream publication | Critical persistence/ingestion; no throttling |
| api | ASGI validation, evidence aggregation, diagnostic reads, background jobs | PostgreSQL/Redis/HTTP responses and queues | Critical operator/alert surface and mixed jobs; no whole-service throttling |
| sentinel | Source decode, volume merge, discovery, watcher buffers, publishers | Solana RPC/WebSockets, provider HTTP, Redis/event-log, outbox | Critical detection/alert/collection; preserve cadence |
| collector | Stream consumption, track tasks, price/liquidity snapshots | Redis groups/PEL, market RPC/HTTP, PostgreSQL observations | Critical prospective evidence; preserve cadence and recovery |
| entities | Stream resolution, funding scans, batch computation | Redis groups/PEL, PostgreSQL, providers/rate-limit retries | Important processing intertwined with intake/recovery; not approved for throttling |
| web | Next dev compilation/HMR, JS heap, response rendering | File watchers/build artifacts, API proxy/HTTP | Important UI; no live process/priority/memory changes |
| maintain | Three concurrent loops, subprocesses, health/watchdog checks | PostgreSQL research/evidence writes, filesystem pass log, dependency probes | Mixed critical and expensive work; never blanket-throttle |

Specific dependency traces inspected:
- `services/event-log/src/event_log/api.py`: transport connection/retry and ASGI
  lifetime. Redis availability is not proven by HTTP alone.
- `services/sentinel/src/sentinel/cli.py`: watch tasks, publisher, volume monitor and
  45-second discovery. Configured volume/fee/depth cadences remain unchanged.
- `services/post-migration-collector/src/post_migration/service.py`: Redis intake,
  track handling and existing bounded database recovery; tracker has 20s/60s
  observation cadences. Gaming never changes these or performs new backfill.
- `services/entity-resolver/src/entity_resolver/service.py`: stream handling, PEL
  recovery every5seconds and scheduled batches. Batch delay could affect downstream
  evidence; no approval to change it.
- `scripts/run_genesis_service.py`: maintenance V2 every10seconds has a frozen
  admission window; research every60seconds creates prospective scores/decisions/
  plans, and watchdog/health share its loop. All remain protected.
- Slow maintenance (`learn-success`, `recompute-performance`) runs every21600s;
  CLI calls SuccessLearner/store recomputation, updates outcomes/wallet-performance.
  CPU-heavy does not mean safe to defer. Both remain unchanged pending impact proof.
- `apps/web/src/components/command-center/CommandCenter.tsx`: existing6s live poll
  already avoids stacked in-flight requests. No polling change without latency data.

No explicit GPU compute library call was found in the searched service/package/
script Python sources. This is not proof of zero GPU use: browser compositing,
third-party/native code and drivers are outside that search. No GPU configuration,
process priority, power plan, affinity, driver or game setting is changed.

**Approved isolated noncritical roles:** `offline-path-report` and
`offline-latency-report` are explicit fixture-only read-only report roles, not names
of active worker loops. `analyze_intelligence_execution_paths.py` reads and formats
existing evidence; report generation is separate from frozen V2 capture. No report
is run against production or registered as a background job here. No production
command mapping is installed. Unknown roles, including Atlas, are rejected.

## Normal and Gaming policy

New `scripts/genesis_gaming_policy.py` has no OS/process/network/file/lifecycle
operations. It is not imported by any production launcher, service, UI or CP77 path.
No CLI/environment switch, autostart, game detection, saved activation or controller
panel exists. Closing a panel cannot invoke this independent in-memory controller.

Default Normal permits existing classified work; the fixture bookkeeping cap64
active reports is an invariant, not an OS throttle. Critical/important service
roles and all3 maintenance loops always remain admitted and unchanged, even if
optional report ownership becomes stale. No cancellation or process termination.

Explicit trusted in-process isolated opt-in plus actual LaunchObservations is
required to select Gaming. Each report admission checks fresh native owner,
authenticated maintain session/generation and clock ordering. Copied public status,
PID reuse/replacement, retired observations and stale generations cannot authorize
control. HOLD is sticky; returning to Normal releases restrictions but does not
restore Gaming authority. Controller restart starts Normal with no restored trust.
This is observation-bound fixture admission, **not lifecycle authority**.

Gaming permits at most1approved report at a time and one new report admission per
60seconds. Busy/cooldown decisions return false immediately: no unbounded queue,
retry loop, busy polling or waiting memory. Already-admitted work remains active
through transitions and exceptions release its slot. Caller must respect the
admission result; no production executor is wired. Critical loop admissions do
not use this throttle. No arbitrary OS PID controls or callback execution.

## Proposed budgets versus measurements

| Measure | Normal | Gaming proposal | Measured/certified |
|---|---|---|---|
| Whole-host normalized CPU for optional reports | Existing behavior | <=5% 60s rolling average | Unmeasured; not enforced by admission |
| Additional optional-report RSS | Existing behavior | <=256MiB | Unmeasured; no memory limit applied |
| Optional-report disk I/O | Existing behavior | <=1MiB/s 60s average | Unmeasured; no I/O shaping |
| Optional-report external network | Existing behavior | 0KiB/s | Role requirement; no network sandbox/command mapped |
| Optional GPU compute jobs | Existing behavior | 0 | Role requirement; no driver/process enforcement |
| Critical capture/alert p95 latency regression | Existing behavior | <=5% versus matched Normal run | Unmeasured; requires same offered load + freshness/loss checks |
| Optional report concurrency/admission interval | Existing behavior | 1 / 60seconds | Deterministic isolated behavioral tests only |

Budgets are validated bounded proposal fields, not achieved performance claims.
No gaming FPS/frame-time/CPU/GPU improvement is claimed. Future measurement must
compare repeated matched Normal/Gaming workloads with critical capture/alert latency,
loss, backlog and freshness, count all descendants/dependency cost, and reject
activation if critical quality or resource budgets fail. Do not run production or
pause evidence just to collect such measurements without separate authorization.

## Ownership continuation audit after inactive policy tests

The installed Next `next/dist/cli/next-dev.js` forks `../server/lib/start-server`
with inherited stdio, exchanges `nextWorkerReady`/`nextWorkerOptions`/
`nextServerReady` over IPC and can restart on its special restart exit code.
It may set a worker max-old-space-size based on half total host RAM. This is a
configured heap ceiling, not measured RSS. No dependency source modified.
A parent observation key cannot be inherited as worker authority; the next step
needs per-worker private IPC proof, fresh native descriptors, generation-bound
restart retirement and socket joining. Existing closed-tree rejection stays HOLD.

Maintenance loop/job manifest and child source checks remain as GB-03. Real recurring
business workloads and descendant retirement still need isolated DB fixtures; no
Gaming deferral is authorized for them. Existing Redis pool observation and cohort
registration do not provision child-owned credentials/factories across every direct
client, reconnect and socket join. Full production client attribution remains
AMBER/HOLD. No attempt to activate these paths during Gaming work.

## Safety, preservation and certification

All29 pending tracked files fingerprinted before work and required to remain
byte-identical. Four migration edits, CP77/untracked work and protected saved-state
copies preserved. Only new policy/test/report files are in this checkpoint scope.
Production Genesis never started. Atlas read-only baseline/final identity checks;
no Atlas configuration/container changes. Start/Stop/Restart/Gaming UI disabled;
Redis continuous durability and full cooperative shutdown HOLD. No live trading,
signing, wallets, orders, automatic startup, VPS or destructive Docker operations.

Exact final test counts, container/snapshot checks and commit/push identity are
recorded at certification completion and in the append-only canonical handoff.

## Full remaining roadmap

1. Certify hierarchical Next dev/HMR/npm worker identity/restarts/socket joins.
2. Certify real recurring maintenance source manifests, worker completion and
   descendant retirement without changing prospective cadence or frozen research.
3. Complete child-owned Redis factory/private provisioning, sync/async/pool/direct/
   reconnect attribution and joint native socket evidence with generation retirement.
4. Integrate any future Gaming executor only after workload impact, ownership and
   measured repeated resource/critical-latency budgets pass; no production activation
   or lifecycle authority inferred from this inactive foundation.
5. Reconcile saved final acknowledged boundary and PostgreSQL/MinIO/frozen evidence
   recovery; separately approved manual startup, cooperative drain, independent
   snapshot restore and exact-owned Start/Stop/Windows lifecycle certification.
6. Preserve all existing V2 adequacy/descriptive research, provenance contradictions,
   runtime/provider/#439, Intelligence Engine/Command Center/product/Discord alerts,
   SaaS/account/entitlement/audit/security milestones. No new live-capital authority.

## Final certification results

- Focused policy behavioral tests: **41 passed, 0 failed, 0 skipped**, exit0,
  0.21seconds. Includes normal/no-env-activation, reversible admission/concurrency,
  all protected roles, invalid budgets, PID/identity/generation retirement, concurrent
  reports, exception cleanup, unknown/Atlas role rejection, clock regression and
  restart-safe defaults. No production process or OS resource control is exercised.
- Full canonical suite: **1,850 passed, 17 skipped, 0 failed**, exit0, 511.75seconds.
  Existing Discord audioop warning. Text/JUnit saved under ignored logs/gb04.
  Existing isolated Redis/native authentication regressions included; opt-in Next
  production fixture remains separately certified by GB-03, not rerun here.
- Python compilation and git diff checks pass. No unavailable Ruff/mypy claim.
- All29 original pending tracked files byte-identical to the GB-04 initial SHA256
  manifest. Both protected RDB copies retain original SHA256
  658276641112471b58814233a3239f2d2b2413982a7fbf6bda4c1e184deaddfe.
- All5 original Genesis/Atlas container IDs/states/start timestamps unchanged.
  Only the exact retained empty isolated tmpfs Redis test fixture was started for
  regression tests, verified empty/no foreign clients, stopped and retained.
  No production startup, data writes, counter queries or market-freshness claims.
- Commit scope exactly3newfiles: scripts/genesis_gaming_policy.py,
  tests/test_genesis_gaming_policy.py, docs/GENESIS_GB04_REPORT.md.
  AGENTS/master roadmap/handoff receive append-only continuity outside this commit.
  Git commit/push identity is recorded there after remote verification.

Verdict: inactive foundation GREEN; resource benefits UNMEASURED; production Gaming
and ownership AMBER/HOLD. Controls remain disabled. No production resource limits
or existing research/maintenance concurrency/schedules were modified.
