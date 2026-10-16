# GB-09A protected runner integration

October 15, 2026 America/Chicago. Base/HEAD/upstream:
66485adb86f23f85d5dc303af7955d513f38d89a,
branch chatgpt/443-intelligence-asof-dataset.
Overall AMBER/HOLD for complete supervisor/cross-process lifecycle. Inactive integration
only; no production activation. Partial staging is allowed only after final canonical
and independently reviewed HEAD-only candidate checks; original pending work stays local.

## Original runner preservation

Before any edit, exact original bytes were saved (exclusive new-file creation) in
ignored logs/gb09a/runner-pre-edit.py; original SHA256 matches the original29
manifest logs/gb04/pending.json. Exact git diff --binary retained separately as
runner-pre-edit.patch. No reset,checkout,clean,stash,restore or unrelated overwrite.
The original runner patch contains existing web capability/bootstrap,child pipe,
web adapter and completed_workers changes; all remain present.

Original added blocks are independently matched in the new runner; a complete
pre-edit-to-GB09A-only delta is saved as runner-new-only.patch. All other28protected
tracked files remain byte-identical. The saved original bytes/patch/fingerprints
remain the reference, not a modified baseline. New preservation proof records
original and new SHA256 and matched blocks. CP77 witness and protected RDB copies
retain original hashes. Frozen worker/policy/cadences/research sources untouched.

## Exact new integration

New scripts/genesis_maintenance_binding.py supplies an explicit isolated
MaintenanceBinding, not a cross-process coordinator. No environment/CLI/default
activation or lifecycle UI exists. It accepts typed maintain observation/manager
and cooperative gate, complete retirement/idle witnesses, and isolated=True only.

The binding authenticates the full already-attested launch challenge and supervisor
manifest with the private launch key. It requires the same process PID, command
hash, repository identity, service and generation. Native FILETIME creation ticks
must agree with the independently captured observation creation timestamp at its
microsecond precision; each source still revalidates its own exact native identity.
No keys/proofs are published in status/logs/argv. Swapping observers, registries,
manager objects, native identity or generation latches HOLD. A new binding cannot
replace a manager's existing authority. This is in-process private trust binding,
not proof of a remote coordinator or independent external launch authorization.

Runner gains explicit install_maintenance_binding. It rejects repeat/dirty
installation and still rejects the formerly invalid combined controllers unless
this exact binding verifies. The selected service must be maintain. Default None
preserves ordinary and existing CP77-only runner behavior.

The manager's shared boundary now optionally consults the installed binding at
loop/job admission. A bound job must have a live root ticket; direct-manager and
alternate-manager attempts cannot bypass root admission. Unbound registries remain
outside this certified boundary and HOLD for global claims.

Runner supervisor_job/run_admitted_job use the same root when explicitly bound.
Existing stop_event and wait behavior now coexist with observation: all three real
loop decorators use cooperative gate accounting and manager observation together.
Per-attempt root admission precedes observation job admission, so a previously
admitted job can finish after fencing without creating a new root ticket.
FencedAdmission is treated as expected only when verified cooperative stop is
already requested. Production retry counts/backoff and 10/60/21600-second cadences
are unchanged. No frozen worker/business logic is edited.

Direct writer coverage in bound mode:
- Dependency-watchdog already runs through run_admitted_job; it now shares this
  authenticated root. No real Docker watchdog operation was executed by the tests.
- append_log, ownership state and aggregate health file writes obtain root tickets.
- V2 pass provenance start/finish encloses the existing observe_pass in one admitted
  root operation. The frozen worker invocation and recorded pass semantics remain.
- Runner-owned log-reader thread borrows only its still-live parent's private job
  ticket. Unknown/expired tickets and reader exceptions HOLD. A reader still alive
  after the bounded join prevents success. Raw reader writes remain charged to
  that admitted parent rather than receiving post-fence fresh authority.
- Combined-mode child native registration occurs before private continuation,
  using the actually spawned authenticated command. Original CP77-only registration
  remains unchanged. Registration-race failures HOLD; the exact still-private stdin pipe is closed on
registration failure so no private capability or application continuation is released.
No process signal/forceful cleanup occurs. A behavioral inert-capture test covers both
success ordering and rejected ownership.
- Ordinary final exit logging is omitted in bound mode after stop rather than
  issuing a new post-fence business/file admission. This is an explicit isolated
  mode difference; default production logging is unchanged. Control audit records
  use the existing cooperative persist callback and are not global write closure.

The authenticated shutdown receiver, if explicitly installed, verifies the bound
manager/loop/owner and independent zero-descendant/unresolved-writer proof after
cooperative gate drain and before adding a bounded maintenance acknowledgement.
Missing evidence or callback exceptions HOLD. The returned scope explicitly denies
global business-write or process-exit authority. Root/manager locks are not acquired
in reverse order during final verification.

## Covered / uncovered authority inventory

| Path | Evidence | Status |
|---|---|---|
| Same native supervisor/generation, exact observer/manager/gate | Typed binding, private HMAC and native identity checks | Isolated tested |
| Alternate observer registry or manager in installed binding | Refusal and shared HOLD tests | Isolated tested |
| Direct bound manager jobs without root admission | Missing ticket rejection | Isolated tested |
| Separate unbound LaunchObservations registries / OS processes | No global enrollment/IPC broker implemented | HOLD |
| Actual runner stop/wait/loop helpers | Three concurrent fixture loops, cooperative drain and join | Isolated tested |
| Actual maintain main preflight/initial ownership writer | Real main entry reaches ticketed write against fixture root, then deliberate sentinel | Bounded pre-loop coverage only |
| Native process/descendant retirement | Exact-owned synthetic process runs real helper functions, parent retained kernel witness | Tested; not full maintenance main |
| Real scheduled SQL jobs, raw SQL/Redis clients | Prior GB06/07 coverage is separate; not enrolled by this patch | Complete business-write closure HOLD |
| Full actual main child registration, retries, all scheduled cycles and daemon thread retirement | Not exercised end-to-end by new native fixture | HOLD |
| Independent cross-process sealed membership and crash/restart coordination | GB09 design only; this binding does not implement it | HOLD |
| CP77 witness packaging | Existing untracked witness reused read-only by opt-in native test | HOLD; no staging authorization |

## Behavioral and native certification

Initial focused bridge/admission run:67passed,3skipped,0failed,23.47seconds.
Expanded focused bridge/supervisor/watchdog/Gaming run:153passed,3skipped,0failed,
92.43seconds. Final binding suite after dispatch-order and failure-test completion:
18passed,0skipped,0failed,25.63seconds (intermediate). Final combined binding/provenance
repair suite:32passed,0skipped,0failed,19.72seconds, including the final registration
failure case and bound/unbound provenance parity. All exits0. Three focused skips are existing
PostgreSQL opt-in native fixtures; no dependency containers were started.

Tests cover formerly rejected combined configuration, actual main preflight and
ownership-file root ticket, three concurrent real runner loop helpers, cooperative
stop/wait, synthetic watchdog/file effects, already-admitted completion, denial of
new admissions, native creation/PID/command/repository/generation/signature mismatch,
unknown manager/direct job, registry substitution, unavailable idle witness,
reader failure and expired ticket. Actual nested run_unfenced AST body executes
with inert captures to prove native registration precedes private release; no
subprocess is created in that ordering test. It is not full-main certification.

Native fixture uses a new exact-owned Python process and private start pipe. Native
PID/creation/executable/command are captured; private registry attestation and gate
identity join are revalidated against the live process. Parent assigns the retained
CP77 Windows kernel job witness before permitting fixture work. It runs the actual
runner's three loop helpers with synthetic callbacks, waits for cooperative stop,
joins threads, exits normally, then parent verifies exit0 and zero kernel processes.
No process kill/forced signal. Any timeout preserves a HOLD-process artifact.
This proves retirement of that helper fixture, not external cross-process authority,
actual scheduled SQL completion or whole production supervisor readiness.

Initial canonical:1failed,1938passed,46skipped,470.80seconds. Exact introduced
failure was the existing extracted-loop test missing the new MAINTENANCE_BINDING
global. Production defines it defaultNone. The harness now explicitly tests both
bound and unbound modes, preserving the one-attempt/10second/START-FINISH assertions
and adding exact pass-record ticket assertions. No safety assertion was weakened.
Initial failure text/XML remain retained. Final canonical rerun: **1941passed,46skipped,0failed**,exit0,360.37seconds.
Existing Discord/audioop deprecation warning only. All1987 cases collected. The46
explicit opt-in skips comprise9PostgreSQL,27Redis/custody,4Next/CP77 and6other native/
packaging cases; exact reasons retained in canonical-skip-reasons.json. No fixture
was enabled against production and no blocked native case is treated as certified.
The new native helper-process case passed in the final canonical run, with all
three loop helper threads joined, normal rootexit0 and zero kernel descendants.
Compilation and git diff --check pass. Final tested source hashes match; original28
other protected bytes, saved original runner bytes/patch, CP77 and RDB hashes match.
No skipped or unrun test is treated as GREEN for its missing integration path.

## Commit/index restrictions

Initial read-only git apply --check --cached of the pre-edit-to-new delta failed
at line61 because HEAD lacks the original pending context. Index remained empty.
Rather than staging the entire runner, an independently owned review tree was
exported using normal git archive HEAD (1036 tracked entries, about6.5MiB).
The original patch's six add/delete groups were reversed ONLY in that review file.
First applying that transformation to the saved pre-edit bytes reproduced exact
Git HEAD, proving the inverse is precise. Applied to the new working runner it
produced a HEAD-only GB09A candidate without the original web/CP77 additions.
Real working files were never restored/replaced; all original pending edits remain.
No CP77 witness or other pending tracked files were copied into the review tree.

HEAD-based isolated review:83passed,4skipped,0failed,exit0,1.13seconds. Skips are
one absent CP77 native witness and three PostgreSQL opt-in cases. This is not a
clean-checkout native pass claim. The native fixture's six actual runner helper
functions are structurally identical (AST comparison) in working and candidate
sources; new binding/manager/tests are byte-identical. Full-main retirement still HOLD.
Candidate SHA256 and independent results are recorded under logs/gb09a.

Only a normal HEAD-compatible partial patch will stage the runner. Staged bytes
must exactly match this independently tested candidate, and all other staged files
must match reviewed GB09A sources. After commit the original runner diff must retain
exactly the saved original add/delete groups, plus the original other28 pending
fingerprints. No full-runner git add, CP77 staging, low-level blob/ref manipulation,
reset/clean/stash or history rewriting is permitted. Commit/delivery identity will
be recorded in continuity after actual verification, not assumed here.

## Remaining roadmap and next execution

1. Deliver only the independently tested HEAD-compatible GB09A candidate after
   exact index verification; preserve the complete original pending runner patch
   and all other28 protected files locally. Verified SHA is recorded in continuity.
2. Extend safe native fixture to the actual complete maintenance main, child factory,
   private registration, full scheduled job cycles, direct writer accounting and
   independent daemon/main-process retirement. No rewritten runner substitute.
3. Implement the separate GB09 authoritative sealed multi-registry/process coordinator
   with private member provisioning, processed drain acknowledgements, crash/restart
   reauthorization and unknown/disconnected member HOLD. This patch is not that broker.
4. Reconcile interrupted real jobs and complete child-to-Redis/SQL attribution; keep
   bounded maintenance admission, business-write closure and lifecycle distinct.
5. CP77 packaging requires separate explicit authorization; preserve all pending files.
6. Unsafe Next/HMR integration remains HOLD; Gaming remains inactive/unmeasured.
7. Redis continuous durability/migration, final ACK and recovery remain HOLD. Historical
   Redis helper137 stays UNKNOWN; no new Redis control operation was performed.
8. Start/Stop/Restart/Gaming disabled; no production Genesis, autostart, VPS, resource
   controls, live trading, signing, wallets, orders or Atlas operations.
9. Preserve full frozen V2/provenance/runtime/provider/#439/Intelligence Engine/
   Command Center/product/Discord/SaaS/account/entitlement/audit/security history.

Exact implementation scope: modified scripts/run_genesis_service.py (original patch
preserved) and scripts/genesis_maintenance_observation.py; new
scripts/genesis_maintenance_binding.py and tests/test_genesis_maintenance_binding.py;
compatibility coverage in tests/test_genesis_pass_provenance.py.
New docs/GENESIS_GB09A_REPORT.md. Earlier untracked GB09 report remains untouched.
Append-only local AGENTS/canonical-roadmap/handoff updates are not implementation
staging. All unrelated work, snapshots and CP77 artifacts retained.

## Delivery verification contract

Exactly six intended commit paths: scripts/run_genesis_service.py (partial only),
scripts/genesis_maintenance_observation.py,scripts/genesis_maintenance_binding.py,
tests/test_genesis_maintenance_binding.py,tests/test_genesis_pass_provenance.py,
docs/GENESIS_GB09A_REPORT.md. No CP77, original web adapter, migration, configuration,
.env, snapshots, logs or other pending changes may be staged. Exact delivery SHA,
remote verification and post-commit original-patch-group comparison belong in
append-only AGENTS/master-roadmap/handoff. Full global/production authority stays
AMBER/HOLD regardless of a scoped commit. No PR/main merge/remote CI/signature claim.
