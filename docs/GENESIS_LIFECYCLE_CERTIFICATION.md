# Genesis guarded lifecycle — Checkpoint 72 design and component certification

This is a forward implementation contract, not a certified full-runtime shortcut.
No full Stop, dependency restart, production adapter activation or cutover was
performed. The running seven-service installation remains collecting.

## Current shortcuts and actual gaps

`Genesis.lnk` targets `cmd.exe /d /k Start-Stinky-OS.cmd` in this repository.
The no-argument wrapper selects `start_genesis.py --core-only`, recovering exactly
event-log, api, sentinel, collector, entities, web and maintain. Optional paper
services require explicit `--full`. `--skip-sync` cannot waive ownership checks.
Existing dependency startup uses the three existing named containers, without
creation/removal, and probes PostgreSQL, Redis and MinIO before starting apps.

`Stop Genesis.lnk` targets `Stop-Stinky-OS.cmd`, which delegates through
`stop-stinky.ps1` to `safe_genesis_stop`. It still performs application-only forced
termination. It does **not** implement the permanent graceful full-runtime Stop.
Do not describe the user's previous manual dependency stops as shortcut behavior.

The maintenance watchdog previously used only names/states from `docker ps` and
did not share the Start/Stop lock. `recover_watch_dependencies` now checks all
three container identities, project/service labels, expected ports and writable
volume mounts before starting any stopped container by exact ID. It shares
`application-start.lock` and verifies unchanged identity/configuration/storage
afterward. Healthy containers are untouched. Engine failure, unknown ownership or
lock contention has no destructive fallback. This change takes effect on a future
runner launch; the already-loaded supervisor was not restarted or hot-patched.
Successful watchdog submission is not application or dependency readiness proof.

## Full START sequence to certify before deployment

1. Acquire the shared lifecycle lock. Verify exact shortcut/repository/environment
   and independently pin the three existing containers, images, volume identities,
   labels and ports. Reject conflicting storage writers and ownership ambiguity.
2. Inspect native application ancestry, executable/argv and creation identities.
   Do not trust PID files; recognize healthy services, reject duplicate/orphan
   chains and leave all unrelated processes alone.
3. Start only stopped owned dependencies, by verified ID. Never recreate them.
   Wait for genuine PostgreSQL/Redis/MinIO readiness. Engine unavailability requires
   an actionable failure, not Docker Desktop restart or container cleanup.
4. Independently verify persisted Redis loading against the protected shutdown
   recovery boundary, required schema, frozen registry/plans/results and zero
   authority. A volume, PING or BGSAVE-success message alone is insufficient.
5. Start only missing members of the seven-service core set. Require exact native
   supervisor/child identities, fresh ownership heartbeats and real HTTP health.
6. Verify advancing captures, stream progression and genuine maintenance/V2 work.
   Report external connectivity failure as collection DEGRADED; preserve local
   healthy infrastructure and missing observations. Do not invent forward data.

## Full STOP sequence to certify before deployment

1. Acquire the same lock and independently verify every owned application tree,
   including any optional Genesis process actually present. Pin native handles and
   creation identities. Reject unknown descendants, PID reuse or ambiguous roles.
2. Cooperatively prevent supervisors, maintenance threads and queued tasks from
   creating new work. Fence every registered Redis writer server-side, exclude
   anonymous/unsupported writers, drain all durable intents/replies and verify
   fresh native connection registration. A process-count plateau is not proof.
3. Capture the final complete Redis source state **after** quiescence. Create a
   fresh guarded snapshot and a separately protected copy without overwriting
   backups. Check checksum/structure and independently restore it in isolation.
4. Compare before/after/restore key contents, stream IDs and ordered payload bytes,
   group cursors, consumer identities and all pending delivery metadata using the
   strict existing RDB gate. Recheck writer/native/server identity and fencing.
   Reject unresolved acknowledgements, unregistered writers, changed source state,
   expiry, unsafe eviction, broken copies or missing restore evidence.
5. Only after the recovery boundary passes, request graceful supervisor/child
   completion, allow bounded active jobs to finish, and verify absence. Any forced
   escalation needs separately reverified ownership and explicit diagnostics.
   Never replace cooperative shutdown with broad Python/Node/process killing.
6. Recheck container identities/storage. Gracefully stop exactly stinky-postgres,
   stinky-redis and stinky-minio in place, verify stopped state and preserve IDs,
   volumes, snapshots and databases. Atlas, Docker Desktop, the V2 test database
   and unrelated/checkpoint containers are outside the operation.
7. Report VERIFIED completion only after all proofs pass. Repeated Stop is a no-op
   only when actual application/dependency absence is verified. Preserve current
   recovery artifacts on any partial failure; never silently restart or reset.

`verify_guarded_stop_snapshot` is an **inactive read-only gate** for step 4. It
requires authenticated fenced/drained broker state, complete participant/native
connection checks, fresh server identity and noeviction, no expiry, identical
protected snapshot bytes, an independent checksum checker and matching restored
semantic evidence. It rechecks closure after checking the artifact. It neither
creates a snapshot nor controls processes/containers; trusted native controller
and independent evidence acquisition remain required. Unit checksum/restore
fixtures are explicitly simulated, not production persistence certification.

## Certification matrix and remaining prerequisites

| Requirement | Current evidence | Remaining certification |
| --- | --- | --- |
| Core-only selection, ownership, duplicates, repeated Start | Existing isolated launcher tests | Actual cold full-runtime lifecycle under guarded approval |
| Watchdog ownership and Start/Stop serialization | New behavioral tests; future-run repair | Future loaded-runner activation and controlled observation |
| Final snapshot integrity/fencing refusal | New read-only gate tests, strict existing recovery comparator | Fresh complete native writer boundary plus independent real final-RDB restore |
| Graceful app stop and maintenance thread cancellation | Design only; current Stop remains forceful | Cooperative runner/child cancellation outside frozen V2 code |
| Exact three-container stop/restart | Existing startup component guards; no full Stop implemented | Native controller plus persistence-qualified live lifecycle |
| Redis restart durability | Prior saved RDB point independently restored; new writes remain volatile | Complete custody capacity/epoch/controller rollout and guarded durability migration |
| Internet outage and abrupt shutdown | Preserve/degrade requirement; no destructive fallback in repaired watcher | Bounded external-degradation tests and honest unwritten-data limits |
| Atlas isolation | Exact pre/post identities preserved; mock isolation tests | Maintain at every later lifecycle step |

Production adapters are inactive. Real legacy writers are not a certified fenced
registry, Redis still disables AOF/automatic RDB and uses allkeys-lru, and throughput
acceptance remains separate from byte-integrity success. Consequently full Stop
and production activation remain blocked. No guaranteed graceful shutdown or
loss-free recovery is claimed for abrupt Windows/power interruption.
