# Read-only supervisor pass status

`GET /v1/intelligence/execution-v2/supervisor-passes` reads the activated local
pass journal through the existing bounded reader: at most 1 MB, 100 retained
events and 20 returned passes. It never writes telemetry or experiment data.
Unknown or malformed/conflicting journal data returns UNAVAILABLE without passes.
An empty observed journal remains distinct from a disconnected journal.

The response keeps START_ONLY/END_ONLY/COMPLETE pairs explicit. Missing start,
finish, exit code or duration remains null. FINISH exit zero is an observed
child success, not proof of source coverage, recovery, profitability or adequacy.
The last successful complete ordered pass must match the local current supervisor
state and start boundary. That state match is not live native process identity
verification. Observer UUIDs never count as experiment sessions.

Sleep intervals are wall-clock differences between recorded boundaries of
consecutive passes from the same observer/PID, not independently measured sleep
timers. A negative interval or a preceding clock regression remains unavailable.
Intervals over 30 seconds are descriptive warnings, not downtime/failure claims.
Pass freshness uses a 300-second diagnostic threshold, not frozen policy timing.
Recorded clock regressions remain visible rather than corrected.

Collection freshness is independent: one read-only, time-bounded SQL query uses
the latest 50 V2 plan mints and indexed per-mint latest-capture lookups. Its DB clock
is labeled separately from the host supervisor clock. Disconnected collection
data remains unavailable while valid local pass observations can still be shown.
The SQL statement is limited to 1.5 seconds and the DB stage to 3 seconds; journal
work is offloaded with a 3-second response deadline. Responses contain no raw
log lines, command arguments, exception messages or provider credentials.

The UI is inside the existing collapsed details, loads on expansion/manual
refresh only, cancels on close and adds no polling. Snapshot age, retained scope,
partial pairs, duplicates, clocks and source identity remain explicit. No frozen
worker/policy/migration/evidence/adequacy changes or maintenance restart are needed.
