# Private child bootstrap and coordinated Redis registration

Resumed October 15, 2026 America/Chicago. Base
`407a295758c53a59fe3a26dfc86bf6044437ebea`, existing branch
`chatgpt/443-intelligence-asof-dataset`. Isolated certification only.

## Implemented boundary

The inactive supervisor observer can explicitly install a typed private Python
child channel. The real runner then substitutes the fixed private entry command
and provisions stdin only for that installed context. With no observer/channel,
ordinary behavior is unchanged. The original CP77 web stdin changes remain
separate and uncommitted. Nothing installs a production observer automatically.

Each child gets its own random key through its inherited private pipe, not the
supervisor's key. Its challenge binds the exact supervisor launch, service,
generation, child PID/creation/image/command, nonce and bounded expiry. Independent
native verification and ancestry checks bracket processing. Duplicate identities,
replay, PID replacement, wrong signatures and stale generations HOLD.

The handshake distinguishes initial proof, controller processing, signed child
installation, controller confirmation and final signed **dispatch-ready** receipt.
Application dispatch waits for authenticated parent confirmation and native
revalidation. The parent waits for dispatch-ready before descendant inspection.
No heartbeat or signed client name grants termination, write or lifecycle authority.
Timeout or lost/ambiguous acknowledgement retains HOLD; it does not kill a child.
If the final reply is lost after authenticated dispatch, application work may
already have begun. HOLD is not proof of quiescence, exit or a Redis write fence.
The private transport may retain a blocked daemon reader on HOLD and is not yet
certified as a general production transport or cleanup mechanism.

Actual native certification failed at child verification after controller
confirmation. Code inspection proved an ordering race: confirmation could return
while the child still ran its final native probe, allowing inspection to overlap
temporary probe descendants. The original failure did not retain an exact differing
descendant row, so that particular PID is not asserted. The dispatch-ready receipt
closes the proven ordering gap. The descendant allowlist and
30-second authentication deadline were not weakened. Tests retain failure evidence
and cover forged/missing final receipts and a delayed reader after timeout.

Resumption also exposed deadline exhaustion from repeated whole-machine process
and socket censuses inside identity-only checks. Two measured full censuses took
1.727/1.536 seconds; exact-PID double reads took 0.440/0.472 seconds. The child
entry now brackets two fresh exact-PID native reads, validates command/image/
creation/parent identity and hashes the command in memory. It does not cache an
old census or remove the separate full descendant inspection. The original
30-second authentication deadline remains. Missing/replaced PID, empty command,
oversized/native-error evidence reject in behavioral tests.

Authentication assumes trusted controller/native inspectors and OS-owned private
pipes. It does not protect against an administrator or a compromised process
disclosing its own key. Private material is excluded from argv, environment,
public heartbeat/status and application logs. Published diagnostics contain only
fixed stage names and failure types.

## Redis registration

The child-owned registry view uses a separate child key and revalidates the parent
generation and child identity. It cannot expose supervisor keys. A child proof
alone cannot enable this view; signed installation confirmation is required.

RegistrationCohort declares at most eight exact service/slot members before
connections open. Each physical proof is authenticated independently. Staging
returns COLLECTING_NOT_ATTESTED, never a matched receipt. All declared members,
the complete server inventory, pinned endpoint/epoch and native socket evidence
must pass before any matched processed receipt is returned. Delivery rechecks the
inventory and deadline. Missing, foreign, duplicate, stale, malformed or timed-out
members HOLD the whole cohort. No pending-client exemption was introduced.

Concurrent synchronous and asynchronous real Redis pool fixtures exercise the
existing PoolObservations adapters; async blocking rendezvous runs outside the
event loop. Pool reuse still requires a fresh signed review. No automatic reconnect
or generation-retirement authority was added. Native socket callbacks in these
pool tests are explicitly mocked; the prior independent native socket test remains
separate evidence. These tests do not prove complete production client ownership.

An early async trial overlapped another suite using the same isolated server and
correctly rejected an extra observer. Final certification runs serially against
the dedicated fixture. Unknown-client rejection remains strict.

## Coverage and remaining HOLD

| Service/path | Newly demonstrated | Still unverified |
|---|---|---|
| All seven service identities | Private OS-process handshake and generation binding with synthetic work | Seven actual service workloads and joint socket proof |
| event-log | Fixed real private Python entry, synthetic event_log.cli | Real ASGI/database/publication workload |
| api | Fixed real private Python entry, synthetic stinky_api.cli | Real ASGI/manual queue and background work |
| sentinel | Fixed real private Python entry, synthetic sentinel.cli | Real source/watch/outbox/BRPOP work |
| collector | Fixed real private Python entry, synthetic post_migration.cli | Real DB-backed tracks and observations |
| entities | Fixed real private Python entry plus actual runner/private-channel join with synthetic entity_resolver.cli | Real resolution/reconciliation/funding work |
| web | Identity protocol only; Python dispatcher explicitly rejects | Node/Next process bootstrap, HMR and descendants |
| maintain | Identity protocol only; Python dispatcher explicitly rejects | In-process loops, job children and frozen-worker bootstrap |
| Existing venv runner | Prior native ownership behavior retained and regressed | Private wrapper/grandchild handshake intentionally rejects |
| Redis cohort | Concurrent real sync/async physical pool registration and reuse | Cross-process child-to-factory provisioning, full native socket join and all enabled workloads |

The new child entry does not install a production Redis factory. Private child
capability delivery into actual client factories, coordinated retirement,
reauthorization, direct constructors and joint descendant/socket evidence remain
AMBER. Broker/write accounting, ACL fencing, retention/archive, BRPOP and protected
startup are not bypassed or activated. Combining observational and cooperative
controllers remains explicitly rejected pending certification.

## Preservation and exact scope

All pre-existing tracked modifications were fingerprinted before implementation.
Only the new runner hook is staged from that already-dirty file; a normal reviewed
patch against HEAD preserves the pending CP77 web stdin behavior outside the index.
All four original migration edits and all other pre-existing modified files remain
unchanged. No reset, stash, cleanup, broad staging or low-level Git construction.

Exact implementation/test files:

- scripts/genesis_child_observation.py
- scripts/genesis_private_child_channel.py
- scripts/genesis_private_child_entry.py
- scripts/genesis_redis_client_provenance.py
- scripts/genesis_redis_registration_cohort.py
- scripts/genesis_supervisor_observation.py
- scripts/run_genesis_service.py (only the new inactive hook)
- tests/test_genesis_child_observation.py
- tests/test_genesis_private_child_channel.py
- tests/test_genesis_redis_registration_cohort.py
- tests/test_genesis_supervisor_observation.py

This report and the appended integration-report checkpoint complete the scoped
documentation. Final test counts and exact pushed SHA are recorded in the
certification section and canonical roadmap/handoff.

## Final certification

- Independent exact-index focused/native suite: **106 passed, 0 failed, 0 skipped**,
  exit 0, 208.75 seconds. It uses the exact staged runner and committed accounting
  module, excluding the unstaged CP77 changes in both paths.
- Full canonical working-tree suite: **1,782 passed, 16 skipped, 0 failed**, exit 0,
  293.92 seconds. One existing discord/audioop deprecation warning. No new test
  exclusions or relaxed integrity assertions.
- Scoped Python compilation and working/index diff checks pass. Original pending
  fingerprints and both protected RDB hashes remain unchanged.
- Earlier failing native/deadline trials remain retained as historical evidence;
  the final results above apply to the corrected dispatch-ready and exact-PID code.
- The isolated Redis fixture is stopped and retained only after verifying its
  exact ID/label, separate tmpfs, empty dataset and no unrelated clients. Production
  and Atlas IDs, states and start times remain unchanged.

## Production and next milestone

No production Genesis startup, lifecycle-control activation, credentials/persistence
change, data command, Redis cutover or Atlas operation. The only Redis test instance
uses pinned isolated image/storage and loopback 16603; it is retained after testing.
Protected RDB copies and saved-state code remain unchanged. Prior 20,003-entry
restore evidence remains artifact-only; final acknowledged shutdown completeness
is UNKNOWN. Stopped production dependencies cannot provide fresh DB hashes,
authority counters or collection freshness; no such current certification is claimed.

Production ownership remains AMBER. Start/Stop/Restart/Gaming stay disabled.
Continuous Redis durability and complete cooperative shutdown remain HOLD.

Next: certify private wrapper/grandchild generations, Node and maintenance job
bootstrap, then provision child-owned factories over authenticated private channels
and join actual native socket/server evidence to those service processes. Certify
actual ASGI/DB/background workloads before any production activation. Preserve the
full CP77, V2/provenance/runtime/provider/#439, Intelligence Engine/Command Center,
product/alerts/SaaS/security roadmap and original pending migrations. No live trading.

## GB-03 continuation

The next default-off wrapper/Node/maintenance increment is documented in
`docs/GENESIS_GB03_REPORT.md`. Earlier HOLD entries above remain historical;
the new report distinguishes native isolated coverage from still-unauthenticated
Next dev/HMR workers, active maintenance workloads and production lifecycle authority.
