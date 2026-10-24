# GB-10A — native bootstrap and drain recovery

Base: `5ff7018e69363e6259f076e08a965af309e50ad8`, branch
`chatgpt/443-intelligence-asof-dataset`. This report supplements GB-10 history;
it does not erase its failed runs or grant production authority.

Delivery is gated on the final canonical result and preservation/index review.
Exact delivery SHA belongs in the canonical roadmap and handoff after push.

## Original failure ownership

| Evidence | Expected | Observed and classification | Defensible repair |
|---|---|---|---|
| `test_native_venv_wrapper_private_handshake` | Private wrapper/leaf authentication before30s | Delivery HOLD; repeated native reads consumed deadline. Implementation verification cost, not evidence of an accepted forged identity | Fresh current-process kernel reader; remove duplicate same-phase reads |
| `test_short_venv_job_does_not_race_final_audit` | Source-bound admission and final closed-tree audit before dispatch | Same deadline exhaustion in wrapper path. Short job was not released early | Same phase-cost repair; retain signed dispatch-ready/continuation ordering |
| `test_frozen_v2_cli_help_bootstrap_without_database` | Authenticated real frozen CLI help, no DB access | Same private wrapper deadline HOLD; frozen worker not modified | Same repair; retain invalid DB sentinel and committed-source comparison |
| `test_native_isolated_loop_helper_process_retirement` | Three verified loop arrivals and bounded drain | GB10 canonical failed startup10s; focused revision startup30s then failed drain10s. Fresh self-CIM calls serialized through registry/job locks | Fresh current-process native API bracket; restore original startup10s and retain drain10s |
| Single focused failure | Same helper as above | Not a fifth independent defect | Covered by native drain repair |
| Four intermediate canonical failures | Three wrapper tests plus the helper | Same four identities above, not eight new failures | Exact original tests rerun before broader certification |

Retained diagnostics measured wrapper binding about8–9s, prepare about6s,
accept about4s and confirmation about7s. Confirmation called checked(), repeating
its just-completed native phase. Initial delivery reached HOLD about33s against
the unchanged30s budget. A null failure_stage while its exchange thread was still
finishing is not a precise substage assertion; timings and traces are retained.

The repairs were separated experimentally: the self reader produced10passed /
3failed in the13-case target, fixing the native helper while all three wrapper
tests still failed. Removing redundant same-phase work then produced13passed /
0failed. Do not attribute both failure groups to one untested cause.

## Production-code changes

`scripts/genesis_self_native.py` reads ONLY the current process, twice, using
read-only Windows process/image/command/creation/ancestry APIs. It requires exact
kernel FILETIME stability, own PID, valid parent, bounded image and command. It
hashes the command; no raw command or credential is logged. It uses CIM-compatible
microsecond timestamp representation while retaining complete FILETIME comparison
inside the bracket. Three before/API/after independent CIM comparisons test exact
descriptor equality. API errors fail closed; there is no stale cached fallback.

`genesis_private_child_entry.native(pid)` selects this path only for the actual
current integer PID on Windows. Foreign-PID and batch reads retain the existing
fresh CIM brackets. Retained native handles/creation ticks remain independent.

`genesis_child_observation.py` removes the extra prepare wrapper.verify already
performed by _check, and confirmation's second checked() after _check and the
post-check expiry guard. Later checked() calls still perform a fresh phase. Tests
replace parent, child, executable and command evidence, expire the final check,
and reject replay. Public receipts retain false write/lifecycle authority.

`genesis_wrapper_observation.py` validates initial ancestry from its paired native
census, then audit() independently re-reads the entire native lineage and both
closed-tree/argv census phases before bind can succeed. No observation is cached
across IPC phases. Foreign descendants, argv/image changes and PID replacement
still fail. The private30s deadline and signed final dispatch receipt are unchanged.

The existing uncommitted GB10 runner repair is retained and tested: HOLD stops new
work, wakes cooperative waits, joins its two loop threads within a deadline,
requires registered thread/done evidence, and refuses unresolved retirement.
Default unbound behavior remains unchanged. No process signal or kill is added.

## Actual main native evidence and its limits

`tests/genesis_maintenance_main_fixture.py` invokes imported actual runner.main().
It does not reconstruct its loops. The parent privately provisions the root launch,
processes its proof and signs an exact-target acknowledgement before dispatch.
The root verifies that generation again at main entry. Executable, parent, raw
command digest and driver source are pinned; all source hashes remain stable.

All six actual command constructions execute through the real private child entry,
source manifest, registration, reader and exit paths. Native executable/argv/PID/
creation/ancestry are checked before release. Each child binds a genuine loopback
socket; a marker only selects an endpoint, never authorizes it. Fresh native socket
ownership and the registered process generation must verify before the fixture
permits cooperative work completion. Real retained non-killing kernel jobs verify
each child and the entire root tree.

Passing native proof: six authenticated child roots, six owned sockets, all child
exits0, root exit0, active kernel descendants0, controller and loop threads retired,
QUIESCED within the unchanged10s drain, cadence arguments10/60/21600 unchanged.
Log readers must pass the actual runner's join check before job completion.

The initial harness failed because its final exchange-thread callback tried to
retrieve a service-loop thread-local channel. That is a fixture contract error.
The repair captures the exact registered channel on its owner thread, then the
callback freshly verifies that channel/owner. It does not replace authentication
with success. Failed fixture sources/artifacts remain retained; their processes
retired naturally. Fixture rejection closes only its own private pipe by EOF,
never signals or kills a process. Controller failures remain HOLD.

**Business jobs are synthetic and clearly labeled.** No actual PostgreSQL/Redis
dependency, market source, real maintenance business job or frozen evidence table
is contacted. HTTP probes and dependency recovery executor are isolated no-ops;
their ticket/file paths execute, not production health/recovery. Transient native
inspection helpers are included in kernel closure, not individually certified as
authenticated business workers. This is NOT complete real-job supervisor GREEN.

## Secondary host-census failure, preserved rather than waived

A final-source canonical attempt returned1960passed/46skipped/6failed in578.43s.
Four traces directly report `Command token bound` in capture() while tokenizing
the full host census. The new main fixture and native WorkerGate also returned
HOLD in census-dependent paths; their precise first inner error was not retained,
so historical attribution for those two remains unproven.

An independent exact-owned diagnostic established capture PASS before a known
132-argument process, COMMAND_TOKEN_BOUND while it existed, and PASS after its
cooperative EOF exit. Its native kernel proof has exit0/active0. No argv bound,
ownership assertion, or unknown-process rejection was relaxed. Historical offending
host PIDs were not recorded and must not be invented. Long inline diagnostic shells
are a plausible source; the reproducible fact is the global census bound.

Subsequent native/canonical runs use short commands and no concurrent long inline
diagnostic shells. Unknown/oversized host ownership remains HOLD in normal use.
A quiet test environment is not a production availability guarantee.

## Retained ordered validation

- Initial reproduction:4failed,159.80s; diagnostic/intermediate evidence retained.
- Self reader only:10passed/3failed,102.82s; distinguishes drain from wrappers.
- Exact repaired originals + self checks:13passed,79.45s.
- Bootstrap/phase regressions:59passed/1skipped,270.25s. Skip is opt-in Next.
- Native actual-main/drain cases after fixture repair:6passed,135.58s.
- Existing binding/provenance:32passed,4.80s, original startup10s restored.
- Final ownership-pinned focused suite:57passed,138.38s.
- Independent HEAD-only focused review:55passed/2skipped,28.76s. Both skips require
  the protected CP77 witness, deliberately absent. No protected file was copied.
- Final six secondary-failure rerun and canonical result are recorded below after
  completion. No intermediate failure is counted as a pass.

Ruff and mypy are not installed in the project environment; no pass is claimed.
Compilation, diff checks and final source/preservation checks gate delivery.

## Preservation and commit scope

All pre-edit GB10 sources and the complete tracked diff were retained under
logs/gb10a before editing. Original28 other pending file hashes, original six
runner patch groups, CP77 witness and two protected RDB copies must match before
and after delivery. Exact RDB SHA256:
658276641112471b58814233a3239f2d2b2413982a7fbf6bda4c1e184deaddfe.

Only the new runner delta may be partially staged, using a normal HEAD-compatible
patch proven by reversing the six original groups ONLY in an independent review
tree. No whole-runner add, low-level Git objects, reset, clean, stash or force push.
No CP77, migration, .env, runtime payload, snapshot or unrelated file may be staged.

Intended13 paths: scripts/run_genesis_service.py(partial),
scripts/genesis_private_child_entry.py, scripts/genesis_child_observation.py,
scripts/genesis_wrapper_observation.py, scripts/genesis_self_native.py,
tests/test_genesis_maintenance_binding.py, tests/test_genesis_maintenance_main.py,
tests/test_genesis_maintenance_main_native.py, tests/genesis_maintenance_main_fixture.py,
tests/test_genesis_self_native.py, tests/test_genesis_authentication_phases.py,
docs/GENESIS_GB10_REPORT.md, docs/GENESIS_GB10A_REPORT.md.

Production Genesis remains stopped. No production startup, unsafe Next launcher,
container/volume operation, persistence change, adapter activation, credential
rotation, forced termination, trading, wallet, signing or order authority.
Frozen sources and protected saved-state hashes are checked; no new live database
hash/counter query is claimed with dependencies offline. Atlas remains read-only.
Historical Redis helper137 remains UNKNOWN.

## Complete remaining roadmap

1. Deliver GB10A only after all applicable final gates pass; verify branch/GitHub
   SHA and the exact residual original29 protected changes. Record actual delivery.
2. Continue GB10 isolated real scheduled SQL jobs, actual health/watchdog/file paths,
   client/socket attribution, interrupted SQL and restart uncertainty. Synthetic
   control-flow proof is not real-job completion or global write closure.
3. Authoritative sealed cross-registry/process membership, authenticated drain,
   unknown/disconnected member HOLD and restart reauthorization remain separate.
4. Complete child-to-Redis/SQL and real business-writer attribution; production
   Redis durability, migration, acknowledgements, archival and rollback remain HOLD.
5. CP77 reproducible packaging requires separate explicit authorization. Do not
   stage its pending code or copy its witness to evade the restriction.
6. Unsafe Next/HMR remains HOLD. Gaming remains inactive and unmeasured.
7. Full cooperative production lifecycle, verified final recovery boundary,
   snapshot restore, exact dependency shutdown/startup and live certification remain HOLD.
8. Start/Stop/Restart/Gaming disabled. No production Genesis, autostart, VPS,
   Atlas changes, live trading, signing, wallets or orders.
9. Preserve all earlier V2 adequacy/provenance/runtime/provider/#439/Intelligence
   Engine/Command Center/product/Discord/SaaS/account/entitlement/audit/security
   milestones and permanent evidence/lifecycle laws. No research retuning or backfill.


## Subsequent independent validation checkpoint

The following results occurred after the earlier retained validation
entries. They supplement, rather than replace, historical failures.

- The authenticated actual-main native test passed twice consecutively:
  41.98 seconds and 43.45 seconds.
- Both retained successful proofs reported QUIESCED, six authenticated
  synthetic children, six verified socket owners, root exit codes zero,
  zero active native job processes, and six cooperative completions.
- A focused six-module regression completed with 46 passed, 6 skipped,
  0 failed, in 93.19 seconds.
- The fixture was instrumented to retain controller stage, active PID,
  and traceback locations on future controller failures. The
  diagnostic-only change did not establish or repair the historical
  intermittent failure's root cause.
- The historical canonical result remains 1960 passed, 46 skipped,
  6 failed. No newer clean full canonical result is claimed.
- The current staged runner patch contains only maintenance retirement
  changes. Earlier unrelated runner changes remain outside the index.

These results exercise synthetic control flow. They do not certify
real SQL/Redis business jobs, production writer closure, restart
recovery, or live trading. Production authority remains HOLD / NO-GO.

## Step 75-76: Full active regression and evidence verification

The active pytest suite completed successfully using importlib collection
with explicit root-tests and API-tests helper import paths.

- Passed: 3,689
- Skipped: 93
- Failed: 0
- Errors: 0
- Warnings: 8
- Duration: 338.99 seconds
- Exit code: 0
- Evidence: logs/gb10a/step75-active-results.xml
- Console evidence: logs/gb10a/step75-active-output.txt

The 93 skips require explicit isolated PostgreSQL, Redis, native,
custody, Next, or other protected integration fixtures. They are
not certified passes. Production remains HOLD / NO-GO.

Step 76 independently parsed the JUnit XML and confirmed all
3,689 passes, 93 skips, zero failures and zero errors.

Corrected scoped commit inventory: 14 files, including
scripts/genesis_native_descendants.py. The earlier 13-file inventory
was incomplete. Only the approved 36-addition/1-deletion runner
patch is staged. The other 29 tracked modifications remain unstaged.

The full regression establishes active-suite compatibility,
not sustained production runtime, application write-drain,
continuous intelligence quality, or autonomous paper-trading readiness.
