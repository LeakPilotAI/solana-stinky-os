# Isolated migration coordinator and production boundary

Checkpoint 61 integrates identity evidence, writer fencing, command receipts,
recovery, route exclusivity and abort handling in `redis_migration_coordinator`.
There is no production backend or launcher integration. The coordinator rejects
production names/ports/volumes, unknown images/ownership/activity, extra mounts and
competing volume writers. Only explicitly owned checkpoint61 fixtures qualify.

## Gates and evidence

- Identity comparisons preserve archived identities and differences. Every live
  gate uses an immediate fresh pair; an older observation is not reclassified as
  fresh. Native creation/image/parent/command changes remain rejections.
- Every managed fixture command has a fsynced intent before transmission and a
  fsynced reply record afterward. Unknown replies remain unresolved. XADD replies
  record exact stream IDs and framed ordered field/value fingerprints; metadata
  replies are explicit, with their final group/PEL state covered by full recovery.
- Writer fencing requires the complete registered participant set, no unknown
  clients, zero unresolved commands, and reconciled observed/verified connection
  IDs tied to native owner creation. Client names alone are insufficient.
- A fresh checksum-verified protected snapshot is taken under the fence. Re-read
  the source, verify every retained acknowledged payload, restore to fresh storage,
  verify AOF/always-fsync and actual local WAITAOF evidence, then certify recovery.
- Stop the source before routing the certified target to the common endpoint.
  Reconnect and recheck full state/receipts before releasing managed writers.
  Snapshot/census observations, exact identity differences, gate stage and safe
  failure codes are retained without raw credentials or arbitrary error text.

The ledger is bounded at50,000 commands. It certifies the managed test window;
it is not a reconstructed history of production acknowledgements. A missing or
trimmed acknowledged entry is a rejection, not an implicit retention exemption.

## Abort and rollback

Before source shutdown, an abort may keep the original running only after checking
the retained replies and obtaining a fresh protected recovery point. That backup
covers the fenced point; it does not turn later legacy writes into durable writes.
Persistent backup failure enters HOLD rather than claiming recoverability.

After source shutdown, never restart its stale original loader. A prepared boundary
can support repair only if managed reply counts are unchanged **and** the candidate's
complete current state still matches it. A candidate may have accepted an
unregistered write or a lost reply: ledger count equality alone is insufficient.
Unavailable/different candidate evidence enters HOLD, preserving all current
storage. Do not label HOLD a successful rollback. `last_certified_route` is an
audit reference, not an assertion that an ambiguous active route is healthy.

After writers resume, rollback is a new migration from the CURRENT readable source
with a new fence, settled receipts and fresh protected point. Never reuse the old
cutover snapshot. No two Redis processes may write one volume, and the route must
have exactly one active frontend. Original containers, volumes and backups remain.

## Isolated certification

The full coordinator used loopback-only fixtures on ports16470–16473, fresh named
storage, the pinned Redis7.4.9 image and native ownership for the managed controller.
The initial source had AOF disabled, reproducing the stale-loader risk. A persistent
same-port client crossed container generations. Two writers issued16 concurrent
post-cutover stream writes; all survived fresh rollback. Including two initial
entries and one subsequent rollback entry,19 stream writes and four group-operation
replies were settled. Post-rollback restart preserved payloads, groups, consumer/PEL
ownership and delivery counts under the unchanged checkpoint57 clock rules.

Injected failures at snapshot, preparation, source shutdown, routing, reconnection
and identity stages retained every known acknowledged payload and ended on a
verified original or independent recovery route. Model tests additionally reject
unknown replies, altered/missing acknowledgements, spoofed connection names,
changed native owners, persistent snapshot failure and malformed/unowned scopes.

A real unledgered write was deliberately accepted after isolated routing, followed
by a reconnection failure. The final coordinator entered HOLD, retained both stream
entries, refused stale rollback and proved the candidate's data survived restart.
A final pre-cutover abort also obtained a fresh checksum-verified recovery point.

All fixtures and snapshots were retained. One early attempt safely rejected an
adapter's attempted second volume writer. Another initial fixture could not bind
while an earlier test still held its port; it never started. Subsequent attempts
were serialized after their predecessors exited. These are fixture failures, not
production Redis incidents, and do not override the final observed proofs.

## Remaining production blockers

Production collection was never paused. The existing transport uses direct XADD
with timeouts, retries and approximate retention; it has no complete durable
migration intent/reply registry. Redis consumer group operations also run in
independent service processes. Native suspension, client counts/names and logged
success alone cannot prove every in-flight command settled or every writer fenced.

A production implementation must register all real writers/consumers with native
and connection identities, establish cooperative quiescence and durable receipt
accounting without changing frozen evidence, handle unknown replies conservatively,
and certify actual asynchronous client reconnection and bounded retention semantics.
The native pause watchdog/coordinator-loss path also needs end-to-end production
adapter certification. Until then production readiness is AMBER; checkpoint58's
controller stays disabled and its four changes stay uncommitted. No cutover may be
inferred from this isolated coordinator commit. A future explicitly authorized
checkpoint needs a NEW live recovery boundary and all independent safety gates.

The continuation's read-only runtime check found all seven Genesis application
supervisors absent and no listeners on3000/8010/8002. The three dependencies and
Atlas remained healthy with unchanged identities. The last stored collection
timestamp is not a freshness guarantee. Application recovery authorization is
pending; no recovery or restart was performed during this continuation. These
isolated certifications do not claim that the current application stack is healthy.
