# Authenticated launch and Redis client observations

October 14, 2026 America/Chicago. Base:
`51933b4e2d5e913432c51598fe5be7fb75bc5af6`, branch
`chatgpt/443-intelligence-asof-dataset`. Exact final commit/push verification is
appended to the canonical roadmap and handoff after certification.

## Proven gaps

The current legacy launcher creates a UUID token, passes it through
GENESIS_SUPERVISOR_LAUNCH_TOKEN and records it in the heartbeat under logs. The
launcher checks equality during startup. This supports correlation, not a private,
native-bound authenticated launch generation. Existing raw legacy token records
must not be treated as credentials or imported into the new observation registry.
Their replacement/redaction belongs to separately certified launcher integration;
the pending CP77 launcher/runner files were preserved unchanged here.

Current Redis client call sites include RedisStreamsTransport (redis-streams),
API track.py (api-manual-queue), post-migration service.py (collector-consumer),
entity-resolver service.py (entity-consumer), sentinel manual_track.py
(sentinel-manual-consumer) and optional discord alerter.py (discord-alerts).
Publisher instances can add physical connections. Legacy factories use pools and
do not establish unique authenticated client names/generations. Documented roles
are not proof of actual connection coverage.

The inactive ManagedRedis accounting path already checks physical CLIENT ID and
INFO run_id. This checkpoint does not replace or activate it, alter broker routes,
issue credentials, change ACLs or account for mutations. RedisStreamsTransport's
existing configured-URL logging also needs a redaction review before any secret
bootstrap integration; no real endpoint/credential contents were read or published.

## Scoped implementation

- New LaunchObservations: explicit trusted native verifier and approved descriptor,
  random controller session, monotonic per-service generations, private per-launch
  key, one-use challenge, strict canonical HMAC comparison and bounded deadline.
  Replays, duplicate registration, copied records, PID/image/command/parent changes,
  signed boolean/integer type confusion and missing native evidence fail closed.
- Keys are delivered only through a private fixture stdin pipe after spawn; they
  never enter argv, environment, heartbeat, public status or durable records.
  Controller restart loses trust; stale records cannot restore registration.
- New RedisClientObservations: signed service/launch/slot/connection generation,
  pinned loopback endpoint and server epoch, physical CLIENT ID/GETNAME and native
  socket tuple. A separate observer brackets CLIENT LIST with epoch and observer
  connection IDs and independently rechecks Docker endpoint pins.
- Complete client inventory is bounded. Unknown clients, duplicate names/IDs,
  missing sockets, stale native descriptors and unobserved reconnects HOLD. A new
  observation retires the prior binding without killing or modifying its client;
  a still-connected old client remains unknown and prevents complete attribution.
- Read-only probes use one retained physical socket, finite timeout and no retry
  or automatic reconnect. Physical socket replacement and lost replies reject.
- Native census now includes outgoing connections to configured observation ports,
  allowing independent PID/local/remote tuple attribution for the isolated fixture.

All public statuses keep lifecycle_authorized=false and write_authorized=false.
These are inactive observation utilities, not a new background manager, credential
broker, write fence or launch authority. Trusted-controller/private-process memory
is the security boundary; this is not protection against an administrator or a
compromised process leaking its own key. No automatic production hook was added.

## Native fixture evidence

An actual disposable Windows child received its key/challenge through private
stdin. The controller independently checked its PID, parent, creation timestamp,
image and command fingerprint around native observations. The child processed and
signed the exact challenge. No heartbeat alone or copied public record was used.

A labelled isolated Redis instance used loopback port 16601, separate tmpfs,
128 MiB limit and 0.25 CPU, no production mounts and no production credentials.
Its exact image, ID, label, state and loopback mapping were checked before the test.
The child opened a single physical connection with a nonsecret test name, signed
its actual ID/epoch/socket tuple, and the controller matched that tuple to the
native child plus the independent server inventory. A foreign connection copying
the name produced HOLD. Disconnection produced HOLD. Explicit fresh-generation
reconnection obtained a different client ID and then matched again.

The child exited cooperatively through stdin EOF. Only the exact labelled audit
Redis fixture is stopped/retained after testing. No CLIENT KILL, production Redis
command, credential/persistence change, data command or Atlas lifecycle operation.
Fixture ID and final state are recorded under logs/background-auth-fixture-id.txt.

Two legitimate certification failures were repaired rather than suppressed:
Redis-py CLIENT LIST IDs required exact decimal-string parsing; a missing endpoint
challenge needed an explicit rejection instead of KeyError. Malformed/lossy IDs
still reject, and existing strict comparisons were preserved. Subsequent review
added retained-socket and signed-type/deadline failure coverage.

## Validation

Final focused provenance/native/ownership/saved-state/strict Redis recovery suite:
**139 passed, zero failed/skipped**. Final canonical suite: **1,676 passed,
16 skipped, zero failed**, exit 0, 82.33 seconds. One existing discord/audioop
deprecation warning. Compilation and diff checks passed.
The native test is explicitly opted in for the isolated labelled fixture; ordinary
runs skip that integration fixture, rather than contacting an arbitrary Redis.

Existing source/protected RDB copies remain byte-identical: 6,374,548 bytes,
SHA-256 658276641112471b58814233a3239f2d2b2413982a7fbf6bda4c1e184deaddfe.
The previous independent 20,003-entry restores remain valid artifact evidence.
No claim is added about complete pre-shutdown acknowledgements or current PG data.

All pre-existing modified-file fingerprints are unchanged. Untracked CP77 work,
the four pending migration edits, protected snapshots and prior fixtures remain.
Genesis production and Atlas dependencies remain stopped with original identities.
No production service startup was attempted; current market freshness, frozen V2
database hashes and five authority counters were not queried from stopped services.
No source/evidence/policy or live trading authority was changed.

## Verdict and next milestone

- Authenticated launch observations: GREEN for isolated private-pipe/native proof;
  production supervisor integration AMBER/HOLD.
- Redis observations: GREEN for the isolated single-connection/native/server proof;
  complete production client ownership AMBER/HOLD.
- Recovery regression: GREEN for preserved artifacts and tested verification seams;
  final pre-shutdown acknowledgement completeness remains UNKNOWN.
- Start/Stop/Restart/Gaming: disabled. Continuous Redis durability and complete
  cooperative shutdown remain HOLD. No gaming measurements or improvement claims.

Next: integrate observational proofs into isolated actual supervisor bootstrap and
every real service client factory/physical pool connection, reusing the existing
inactive CP77 controller/broker. Certify wrapper/child identities, async reconnects,
all enabled roles, observer ownership and authenticated generation retirement.
Do not deploy parallel controllers or hot-patch pooled production clients. Replace
legacy raw token persistence through a separately reviewed, default-off bootstrap.
Then reconcile the expected saved-state boundary, frozen database evidence,
PostgreSQL/MinIO recovery and genuinely advancing capture before any separately
authorized manual startup control. Full cooperative drain, protected final recovery
boundary, independent restore and exact owned dependency lifecycle remain later.
Preserve the full master V2/provenance/runtime/provider/#439/Intelligence Engine/
Command Center/product/alerts/SaaS/security roadmap; no unrelated feature expansion.
