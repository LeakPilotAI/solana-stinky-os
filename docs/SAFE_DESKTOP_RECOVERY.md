# Safe desktop recovery

Ordinary desktop startup is serialized by a Windows byte-range lock held through
all service starts and health checks. A concurrent launch fails without starting
another process; the OS releases the lock on exit, including a crash. Stale lock
file contents are not ownership proof.

Recovery checks existing Genesis postgres/redis/minio container names, Compose
project/service labels, expected named data volumes and offset host ports before
any dependency start. It starts only verified stopped existing containers. It never
uses compose up, restarts healthy dependencies, creates/deletes containers/volumes,
changes Redis configuration or trims streams. Dependency health failure blocks
application starts. Schema is checked in a read-only transaction; migrations and
package/environment installation are separate reviewed work.

Services start in the checkpoint 41 order: event-log, API, Sentinel, collector,
entities, frontend and maintenance, then the existing paper-intake/paper-runtime services, using the unchanged supported per-service runner.
Existing native supervisor chains are collapsed across Windows venv wrappers and
verified against repository identity, native creation time and a fresh heartbeat.
HTTP services additionally require HTTP 200. Stale PID files never establish health.
Unverified/stale/orphan/unhealthy/duplicate chains or occupied foreign ports fail
closed without kills or second workers. New starts use a unique launch token and
bounded ownership/health proof; failed proof leaves the new process untouched and
returns failure, rather than retrying a duplicate. Logs are preserved.

Detached hidden processes use the existing breakaway/new-process-group launch flags;
if Windows rejects detachment, startup fails rather than a blocking fallback that
could leave an unverified child. The supervisor keeps its own existing bounded
child-health recovery behavior. Maintenance retains its original allowlisted
stopped-dependency watchdog; healthy dependencies are untouched. No V2 worker,
policy, cadence, registry, plans, results or authority behavior changes.

The shortcut does not invoke the write-capable strict schema migration gate or
invoke the separate paper starter. Existing paper-runtime/intake behavior is retained through the same serialized native ownership path; existing healthy workers are left alone. No Discord notifications or live authority are enabled.

`--skip-sync`, `--keep` and `--skip-install` retain all safety gates. `--sync` and
`--restart` are rejected before startup actions. Ordinary startup uses current
committed files and existing environments; it cannot reset the branch. The separate
Stop Genesis shortcut and migration/application installer are outside this start
path and require their own explicit operational authorization.

Tests use isolated process/container/HTTP fixtures. Live certification reads
existing listeners, process starts, captures, pass records and immutable hashes;
it never exercises destructive outage/restart fixtures against production.
