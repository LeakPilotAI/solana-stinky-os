# Redis preservation and recovery contract

Production Redis must never be stopped, recreated, flushed or reconfigured merely
to test recovery. Preserve its existing keys, stream entries, groups and pending
metadata. Snapshot payloads can contain sensitive evidence: keep them outside Git
with restricted access; report hashes and counts rather than values.

## Checkpoint 54 verified design

Redis 7.4.9's `redis-cli --rdb` full-sync export creates a point-in-time RDB backup
while the primary continues serving clients. Export to a new filename; never
overwrite an existing backup. Inspect ownership, disk capacity, dataset size and
persistence settings first. A fork/serialization can impose brief latency: this
is not a zero-impact or guaranteed no-pause claim.

Verify the RDB using `redis-check-rdb`, then copy it to a separate access-restricted
location. `scripts.redis_snapshot_integrity.inspect_rdb` checks bounded file size,
header and SHA-256; it explicitly does **not** claim checksum validation by itself.
`verify_same_snapshot` verifies copies without modifying either file.

Restore only a working copy into a fresh isolated directory/container, using the
exact source Redis image. Never mount production paths or use production ports.
Use resource limits and loopback-only ports. Census each populated DB; account for
expiry between capture and measurement. The helper's atomic census is per DB, not
a cross-DB snapshot. It bounds key count and total serialized bytes, fingerprints
values/identifiers and records stream IDs, group counters and expiry clocks.
Serialized stream fingerprints include entries, consumers and pending-entry state.
Recovery mismatches fail closed; do not normalize away discrepancies to pass.

The immutable exported file defines the recovered point-in-time baseline. Live
pre-export counts are not that baseline. Writes, acknowledgements, trims and expiry
after capture belong to subsequent production state and are not covered by it.

## Persistence configuration and restart proof

The verified isolated conversion first loads RDB with AOF disabled, enables AOF
on the running isolated dataset, waits for successful rewrite/write evidence,
persists a matching config file, and fsyncs a separate isolated-only test write.
Restart the **same isolated container** and compare the complete census. This
sequence is important: starting AOF against an empty AOF set can omit the intended
RDB data. Do not convert production merely by changing a future startup flag.

`verify_aof_ready` requires enabled AOF, finished/unscheduled rewrite and healthy
rewrite/write statuses. These are prerequisites, not proof of a successful
restart. An actual isolated restart must also recover the captured state and
confirmed durable writes. With `appendfsync everysec`, abrupt power loss may lose
recent writes; no guarantee of graceful power-loss shutdown is made.

The isolated config-file design starts with `redis-server /data/redis.conf`.
`verify_config_file_startup` deliberately rejects unreviewed/conflicting argv.
Production's existing fixed `--appendonly no --save ""` command overrides runtime
settings after restart. Checkpoint 54 reproduced this in isolation. Its snapshot
is recoverable, but production continuous durability remains **AMBER**: no runtime
setting or production command was changed, and no production restart was tested.

Resolving that fixed command while retaining the existing container identity needs
a separately verified startup design. Do not recreate the container or silently
patch its entrypoint. If the constraints cannot all be met, report the exact
conflict for a reviewed decision. A snapshot is a recovery artifact, not evidence
that future live writes are durable.

## Certification boundaries

After every persistence/lifecycle change, test malformed/oversized/corrupt copies,
key/group/pending/expiry mismatches, bad AOF health, startup overrides, isolated
restore/restart and production/Atlas isolation. Production collection freshness,
frozen V2 hashes and zero authority must be verified separately. Do not fabricate
observations or backfill frozen evidence from a Redis backup.

Official references: [Redis CLI remote backups](https://redis.io/docs/latest/develop/tools/cli/)
and [Redis persistence/conversion guidance](https://redis.io/docs/latest/management/persistence/).
