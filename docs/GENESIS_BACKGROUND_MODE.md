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
