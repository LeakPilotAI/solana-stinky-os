# Genesis background mode: read-only foundation

## Verified scope

Step 59 exercises the actual PowerShell heartbeat reader in isolated repositories.
It accepts valid UTF-8 JSON with and without a BOM, rejects files over 16,384
bytes, rejects invalid UTF-8, and closes its file handle on success and failure.
PID, service, phase, explicit timezone, creation-time and freshness checks remain
required. Heartbeats are observations, never lifecycle credentials.

The status script checks native process evidence and inspects exactly the three
named Genesis dependencies. Docker inspection failures return structured UNKNOWN
and UNVERIFIED results. Command lines are fingerprinted rather than published;
decoder/parser errors do not publish input contents. JSON PID values must be
positive integers, without coercion from strings or fractional numbers.

## Optional panel

Run `scripts/windows/Open-Genesis-Background.cmd` manually to open the read-only
window. It refreshes only when opened or requested. Closing it does not stop
Genesis. It installs no Windows startup entry and starts no background manager.
The `-Check` option on `Genesis-Background-Panel.ps1` exposes its view model without
opening a window. The view model is behaviorally tested; visual presentation has
not been certified.

Start, Stop, Restart and Gaming mode controls remain disabled. Neither a matching
heartbeat nor matching Docker labels grants lifecycle authority. The current
process inventory is not complete socket/descendant ownership certification.

## Native ownership and saved-state audit

`python -m scripts.genesis_background_ownership` is an additional read-only audit.
It brackets native TCP socket acquisition with two process censuses and checks
creation identity, executable/command tokens, ancestry, duplicate claims and
possible orphan module processes. Unexpected descendants, foreign listeners,
changing/missing processes and unattributed host Redis connections HOLD. It emits
no raw command lines. Results never authorize Start/Stop/Restart/Gaming.

The Windows child/listener test uses an independently spawned disposable fixture
with an ephemeral loopback port and private stdin EOF shutdown. This verifies
actual native socket attribution and wrapper ancestry, not a running Genesis
service. Historical ancestry, authenticated launch-token custody, complete Redis
server client attribution through Docker NAT and active seven-service closure
remain separate gates. Existing heartbeat checks remain supporting evidence only.

`scripts/genesis_saved_state_audit.py` can export only the explicitly pinned,
stopped original Redis container after checking the complete container inventory
for competing writable production-volume attachments. It streams a single bounded
regular RDB into an exclusive new file, never extracts archive paths and never
overwrites runtime storage. Header/hash checks do not imply checksum certification.
An isolated restore proves the contents of that artifact, not that all pre-shutdown
acknowledged writes were saved. Original storage and retained fixtures stay intact.

## Inactive authenticated observations

`scripts/genesis_launch_provenance.py` binds a one-use private challenge to a
trusted native process descriptor, service, controller session and generation.
Keys stay in memory and the private bootstrap pipe; public status omits keys,
nonces and MACs. Copied heartbeats cannot substitute for proof. A controller
restart discards trust and requires fresh explicit registration. This utility is
not installed in the real supervisor launcher and grants no lifecycle authority.

`scripts/genesis_redis_client_provenance.py` verifies a signed physical-connection
claim against native PID/socket evidence and a separately pinned server's complete
client inventory. Names alone are insufficient. Reconnects require fresh connection
generations; unknown/duplicate/stale clients HOLD. Probes use retained sockets with
bounded timeouts and no implicit reconnect or retry. They issue only INFO server,
CLIENT ID/GETNAME/LIST. The isolated fixture alone sets nonsecret test client names.

These checks do not replace the existing broker, Redis ACL fencing, command-intent
accounting or cooperative shutdown. Real pooled/async clients, native Windows
wrapper chains and all seven actual service paths still need separate inactive
integration certification. Legacy environment-token heartbeats remain untrusted.

The opted-in native Redis test requires an independently labelled disposable
fixture; the environment supplies its nonsecret container ID, never activation
authority or secrets. No test can target production via that fixture guard.

## Remaining gates

1. Restore access to the Docker engine only with appropriate authorization; inspect
   existing dependency identities, volumes and protected recovery evidence.
2. Complete native descendant, launch-token and Redis socket attribution, including
   PID reuse, conflicting owners and identity revalidation before any action.
3. Certify a detached manual startup path with verified persistent recovery,
   readiness, uniqueness and advancing genuine market captures.
4. Complete CP77 authenticated bootstrap and actual active-worker closure. The new
   private startup hook is inactive and its unit tests do not prove native delivery.
5. Establish production Redis durability and cooperative writer drain before
   enabling Stop or Restart. Do not substitute force termination or BGSAVE alone.
6. Measure a live resource baseline before introducing reversible gaming controls.
   No CPU, affinity, GPU, database or power-setting changes have been activated.

Preserve the complete canonical roadmap and existing CP77 work. No Redis cutover,
adapter activation, credentials change, Atlas operation, data cleanup or live
trading authority is authorized by this read-only foundation.
