# GB-05A: inactive private worker gate and cooperative retirement foundation

October15,2026 America/Chicago. Base d3bd90be73961bdf8351c7a46b64e002bdbb043a,
branch chatgpt/443-intelligence-asof-dataset. No real Next dev or production launch.

## Scope and architecture

New `scripts/genesis_next_worker_gate.py` is an explicit in-process controller and
synthetic receiver protocol, not a Next adapter. No production importer, default
installer, CLI/env switch, process creation, signals, priority controls or killing.
Installed Next15.5.23 remains unchanged. It is unsafe to launch the stock dev CLI
for this milestone; its forced paths are still reachable and have not been patched.

Private frames use existing bounded canonical encoding/HMAC primitives. Each worker
gets a new32bytekey and32bytesession, unrelated to its parent observation key, plus
controller and fresh receiver nonces. Private frames must use a dedicated pipe/IPC,
never argv/environment/logs/status or a shared public ownership record. The harness
uses inherited stdin/stdout exclusively for private protocol. Only sanitized phase,
generation/scope flags are exposed by status. Raw challenge/key records remain
trusted in-process state; no durable export or resume-from-record API exists.

WorkerGate requires a typed ChildObservations parent registry. Every worker phase
checks its authenticated parent observation, parent generation, exact native PID,
creation, executable and command hash, direct ancestry and creation ordering.
Configuration pins the worker executable and command hash independently of claimed
ownership. A receiver nonce prevents a copied old bootstrap installing in a fresh
receiver. One live worker per gate, maximum64trial generations; new generation only
after verified retirement. Parent keys, stale child records or duplicate/replayed
proofs do not authenticate the worker.

Handshake:
1. Worker emits its fresh private receiver nonce and PID; controller independently
   captures exact descriptor and prepares a30second challenge with fresh key/session.
2. Worker verifies its own native identity and parent binding, signs challenge.
3. Controller verifies exact proof, parent/native identity and deadline, returns
   authenticated installation receipt. Receiver checks it and local30sdeadline.
4. Worker opens only its fixture-owned loopback listener and signs the ready port.
   Controller independently joins native PID/creation to actual listener ownership
   before RUNNING. This is observational readiness, never business-write/lifecycle
   permission. No real Next module or application work is dispatched here.

A future integration must use a dedicated private Next worker endpoint before
module dispatch, preserve CP77 stdin, gate Next option/application delivery on the
completed controller decision, provision child capabilities separately, and safely
retire replaced generations. This foundation does not authorize installing such a
hook or inheriting parent keys in a real worker.

## Retirement contract

RUNNING -> STOP_REQUESTED -> DRAINED -> COMPLETED -> AWAITING_NATIVE_EXIT -> RETIRED.

Controller rechecks owner and socket before issuing a signed stop request bound to
session/generation and fresh request identity. Receiver latches out of RUNNING
before invoking its explicit fence callback. A false/failed fence HOLDs. Three
strict ordered acknowledgements require typed evidence accepting=false,inflight=0,
unresolved=0. Boolean/number substitution, replay, wrong order, lost IPC, identity
change, unsupported callback or timeout cannot silently prove completion.

A drain acknowledgement is not a completed-work acknowledgement, and neither is
native closure. The third descendant-closure claim only enters AWAITING_NATIVE_EXIT.
Controller finish requires still-authenticated parent and independent native closure
for the exact worker/port. Worker PID need not still be alive at that phase; a
missing/replaced parent or false/missing closure proof HOLDs. Key is discarded only
on verified retirement. Unknown/unresolved state is not reopened or automatically
rolled back. Timeout is bounded30seconds and HOLD, never a forced cleanup trigger.

The protocol does not cancel jobs, stop servers, drain real HMR work, close a remote
process, terminate descendants, restore keys or implement live shutdown. Worker
adapters must supply actual fence/drain/completion/descendant evidence. Local
callbacks are a trusted integration seam, not proof by themselves of workload
accounting. A valid signature alone never authorizes lifecycle action.

## Installed Next paths still unsafe / unchanged

Source audit carried forward from GB-05:
- next/dist/cli/next-dev.js forks server/lib/start-server with inherited stdio and
  NEXT_PRIVATE_WORKER. nextWorkerReady triggers ordinary nextWorkerOptions;
  nextServerReady resolves startup. Worker directly calls startServer on options.
- Worker special restart exit causes a new fork; no Genesis generation retirement.
- handleSessionStop calls child.kill(signal), has default100ms SIGKILL escalation,
  and parent exit handler calls child.kill('SIGKILL'). Signal handlers route there.
- Existing HMR config-change restart calls process.exit(RESTART_EXIT_CODE).

No blind dependency patch and no execution of these paths. Alternatives requiring
separate integration review: a repo-owned dev harness around supported server APIs
with controlled private worker entry/retirement, or a narrowly version-pinned
upstream launcher extension that replaces *all* forced handlers and proves their
unreachability. Wrapping only the outer CLI, extending the timeout or authenticating
a parent does not remove kill-on-exit behavior. Neither alternative is installed.

## Tests and actual native evidence

Deterministic protocol tests cover normal/retired/new generations,wrong key,parent
key rejection,worker nonce mismatch,timeout,parent/worker identity replacement,
PID reuse,duplicate claims,replayed frames,lostIPC,worker crash,missing socket,
failed socket recheck,in-flight/unresolved evidence,out-of-order/duplicate acks,
false native closure,parent exit,restart race and restart-safe HOLD. Gaming tests
retain every critical role and all3maintenance loops unchanged.

Native test launches only a temporary synthetic Python worker with base interpreter,
private inherited pipes and an ephemeral loopback listener. Child independently
reads Windows native own/parent identity. Controller independently checks worker
identity plus bracketing native listener census and actual127.0.0.1binding, then
coordinates fenced idle-work acknowledgements. Socket closes cooperatively; worker
returns normally,exit0. Retained process handle/poll and final native process/socket
censuses must show no root/observed child/listener before RETIRED. No signal or kill
fallback. Failure retains diagnostic PID rather than terminating a process.

**Limits:** parent registry registration in this native test is explicit fixture
scaffolding; it is not native supervisor-bootstrap certification. Work is idle,
not real HTTP/HMR/database jobs. Final census is snapshot evidence,not a kernel
job proof of every transient/grandchild lifetime; real arbitrary descendant closure
remains HOLD. No real Next restart/HMR workload or recurring maintenance certification
is claimed. Actual native failure injection is not silently inferred from mocked
crash/PID/timeout tests.

Initial native test exposed2test-harness errors: temporary script lacked repo import
path,then scaffolding used records instead of _records. Fixed only test setup;
failed outputs retained in ignored logs. Failed workers were never killed. These
were not production or protocol integrity failures. Later socket-callback exceptions
were explicitly made stickyHOLD; assertion coverage added,not weakened.

## Preservation and status

All29original pending tracked files,fourmigration edits,CP77 and untracked artifacts
remain unchanged. Existing saved-state fingerprints are verified separately.
No production Genesis/Atlas startup,Redis connection/configuration changes,live
trading,automaticstartup,VPS,global controls or Docker cleanup. Production counters
and fresh evidence are not queried/claimed from stopped dependencies.
Start/Stop/Restart/Gaming disabled. Redis continuous durability,child-to-Redis
attribution,full cooperative shutdown and production lifecycle remain HOLD.

Exact focused/canonical results and commit/push identity are recorded below and in
the append-only canonical roadmap/handoff after final verification.

## Full remaining roadmap / next safe step

1. Review repo-owned dev server harness versus version-pinned upstream extension;
   no stock dev launch until every forced handler is removed or demonstrably isolated.
2. Integrate private per-worker Next IPC entry,authenticated application-options gate,
   restart generation retirement and cooperative HMR/HTTP/work drain; native real
   worker/socket and kernel descendant closure tests without process killing.
3. Real isolated recurring maintenance schemas/dependencies/source manifests,all3
   loops,success/failure/retry and descendant retirement,unchanged frozen cadence.
4. Child-owned Redis factory/private provisioning,sync/async/direct/pool/reconnect
   ownership and native socket joins with generation retirement. No live activation.
5. GB-04 resource budgets remain unmeasured proposals;production Gaming stays disabled
   until ownership,workload impact and repeated matched performance checks pass.
6. Saved final ACK boundary,PG/MinIO/frozen evidence recovery,full cooperative drain,
   independent snapshot recovery and exact-owned desktop/Windows lifecycle require
   separate certification/approval. No production authority inferred here.
7. Preserve all V2/provenance/clock contradictions/runtime/provider/#439/Intelligence
   Engine/Command Center/product/Discord/SaaS/account/entitlement/audit/security
   roadmap history. No CP78,backfill,live capital,signing,wallets or orders.

## Final certification

- Focused worker/native + Gaming regression suite: **72passed,0failed,0skipped**,
  exit0,13.32seconds;31worker tests plus41existing Gaming tests.
- Full canonical suite: **1,881passed,17skipped,0failed**,exit0,525.56seconds.
  One existing Discord/audioop deprecation warning. Exact XML/text artifacts under
  ignored logs/gb05a; no remoteCI/Ruff/mypy claims.
- New Python compilation and working/staged diff checks PASS. No assertion weakened,
  fixture excluded or existing authentication deadline increased.
- All29pending tracked modifications byte-identical to GB-04 preservation manifest;
  fourmigration edits and CP77 retained,not staged. Both protected RDB copies keep
  SHA256658276641112471b58814233a3239f2d2b2413982a7fbf6bda4c1e184deaddfe.
- Original5Genesis/Atlas container IDs,states,start times unchanged. Only retained
  exact owned isolated tmpfs Redis fixture started for canonical tests,verified
  zero keys/only inspection client,stopped and retained. No production operations.
- Commit scope exactly scripts/genesis_next_worker_gate.py,
  tests/test_genesis_next_worker_gate.py,docs/GENESIS_GB05A_REPORT.md.
  GB-05blocked report remains untracked/preserved. AGENTS,canonicalroadmap,handoff
  receive append-only completion entries outside the implementation commit.
  Final GitHub SHA is recorded there after push verification. No main merge or
  clean-worktree claim:29original tracked modifications intentionally remain.

Verdict: **bounded synthetic foundation certified**. Real Next launcher integration,
real HMR/drain/complete descendant-lifetime proof,recurring maintenance,child-to-Redis
attribution,production durability and lifecycle remain AMBER/HOLD. No Gaming or
production lifecycle control is enabled. The next safe action is review of the
upstream integration alternatives before changing or running installed Next dev.
