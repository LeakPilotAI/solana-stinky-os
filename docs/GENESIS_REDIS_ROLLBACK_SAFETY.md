# Fresh-boundary Redis rollback and identity evidence

Checkpoint 60 certifies isolated safety primitives, not production deployment.
Production Redis was not paused, stopped, reconfigured, replaced or migrated.
Checkpoint 58's four working-tree changes remain preserved and uncommitted.

## Identity evidence

`genesis_identity_journal` sequences BEFORE/DURING/AFTER capture around a caller's
independently authorized actor and always attempts AFTER capture following resume.
The journal itself grants no process authority. Records are bounded, exclusively
created and fsynced; exact differences are persisted before rejecting a gate.
Capture includes native PID, creation ticks, parent, executable image, verified
service/ancestry/role, a redacted command line and exact raw command fingerprint.
Credentials and arbitrary arguments are never persisted. Missing ownership fails
closed with bounded candidate identity evidence rather than fabricated roles.

Classify PID reuse, supervisor changes, ownership changes and verified child churn
separately. Churn remains a rejection, not an exemption. Reject stale/invalid
captures and preserve failure records. The historical 32-node inventory is retained
as an observation; no fixed process count is required. During the isolated Windows
test, two child nodes appeared and their exact identities were recorded before
rejection. Suspension/resumption preserved the fixture's remaining identity tree.
Production captures were read-only: “DURING” means during review, not suspension.

## Rollback procedure and required evidence

Never start the retained original Redis with an old `dump.rdb` to roll back after
new writes. Preserve that original container, volume and every prior backup.

1. Fence every current writer and resolve all in-flight commands. Uncertain
   acknowledgement, unknown ownership or incomplete fencing blocks rollback.
2. Confirm healthy AOF and `appendfsync always`, including local fsync evidence.
3. Obtain a **fresh current** recovery point, complete census and checksum-verified
   RDB with separate protected copy. Re-read the fenced source and require exact
   equality; concurrent writes or a stale boundary must fail.
4. Restore to independent storage, separate from both the original and current
   source. Refuse any active writer on the target volume.
5. Compare every payload byte fingerprint, stream ID, group, consumer, PEL owner,
   absolute delivery clock/count, key and expiry using checkpoint 57's strict gate.
   Enable/persist AOF only after verified RDB loading; prove restart recovery.
6. Stop the current isolated source before activating the certified target on its
   old endpoint. If a separate loader shares the target volume, stop the first
   loader before starting another. Revalidate ownership and volume exclusivity.
7. Verify reconnecting clients, complete current state and durable writes before
   resuming writers. Preserve all source containers and snapshots; never delete
   infrastructure as a rollback shortcut.

`redis_rollback_safety` validates evidence; it does not execute this procedure.
Caller-supplied boolean assertions are not independently authoritative proof.
The production coordinator must establish and retain their real supporting data.
If the current source is unreadable, acknowledgements are unresolved, persistence
is unhealthy or evidence is corrupt, the tested fresh-export procedure cannot
certify rollback. Preserve current storage and stop; never revert to stale data.
Complete storage loss, abrupt-power-loss guarantees and unavailable-source disaster
recovery are outside this proof. AOF fsync is not a hardware-failure guarantee.

## Isolated certification

New fixtures used the pinned production Redis 7.4.9 image, loopback-only ports and
independent named storage. After isolated cutover, three clients concurrently
acknowledged 36 stream writes and a further main-stream entry was delivered pending.
Fresh rollback restored all 37 post-cutover entries, original binary/duplicate
fields, groups, pending ownership and delivery counts. Restart and alternate-loader
proofs passed; the same client/port reconnected. A subsequent acknowledged rollback
write also survived restart. Only consumer activity clocks changed in its declared
AOF replay window; originals and recovered values were retained.

Six negative gates rejected active writers, a stale original boundary, unresolved
acknowledgements, disabled persistence, partial restore and a second volume writer.
The first attempt ended on Windows timeout handling for the stopped endpoint;
all its fixtures were stopped and retained. A fresh second attempt accepted either
connection refusal or timeout as disconnection, without weakening data assertions.
Both attempts' eight containers, volumes and snapshots remain retained and stopped.

## Production readiness

The isolated identity and rollback gates are certified. Production migration
remains AMBER: the disabled checkpoint 58 controller has not been integrated and
certified against this complete protocol, including bounded capture freshness,
watchdog/controller failure, actual full writer reconciliation, fresh production
recovery boundaries and current-write-preserving abort/rollback routing. Do not
activate Compose or retry cutover from these helper commits. A future explicitly
authorized production checkpoint must pass all those independent gates.
