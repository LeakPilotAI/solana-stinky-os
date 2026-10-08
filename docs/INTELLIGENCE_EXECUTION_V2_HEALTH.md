# Read-only V2 collection checkpoint

Run from the Genesis repository and its configured environment:

```powershell
.venv\Scripts\python.exe scripts/audit_intelligence_execution_v2_health.py --compare-since 2026-10-08T02:06:42.151771+00:00
```

The command performs one repeatable-read, read-only database transaction,
validates the registry and stored hashes with the frozen canonical implementation,
then inspects existing local supervisor evidence and bounded log tails. It never
invokes the worker, writes evidence, starts services, or changes the API/panel.
It exits 1 with unavailable metrics on connection or evidence validation failure.
Exception text and raw log lines are never included in the report.

## Interpretation

- Canonical counts and adequacy retain frozen semantics. Pending plans do not
  count toward mature/session adequacy. Missing terminal results after maturity
  are reported separately, still PENDING.
- Market capture freshness and terminal recording freshness are separate.
  `--stale-after-sec` defaults to 300 seconds for diagnostic visibility only;
  it is not a changed observation tolerance or adequacy gate. Old terminal
  evidence alone cannot establish worker failure when no candidates qualify.
- Current supervisor identity/heartbeat is not proof of application coverage.
  Immutable admitted session starts are not session ends or downtime intervals.
  No sessions are inferred or manufactured.
- Missing-price rows retain their recorded UNKNOWN reason. Nearby captured
  timestamps (120 seconds before through 150 seconds after target) describe
  current snapshot coverage, including missing brackets. They cannot establish
  ingestion delay, historical availability, or delayed upstream causation.
  REJECTED rows are never added to a missing-price cohort.
- Optional missingness comparison uses terminal recording-time cohorts before
  and since the supplied cutoff. It reports sample counts and UNKNOWN fractions.
  An empty cohort makes the trend unavailable, not false or zero. This is a
  descriptive comparison, not a statistical/cause/performance claim.
- Log reads are bounded to the last 8 MB of each Genesis collector/maintenance
  log. Counts are matching lines, not incident counts. Truncation and retained
  timestamp range are explicit. Coincident categorized events within a missing
  window are supporting evidence only; no match does not prove no interruption.
  Existing V2 success JSON lines have no timestamp. Their count and log activity
  support bounded activity inspection but cannot prove exact per-run cadence.
- Worker downtime, session end times and snapshot ingestion delays remain
  unestablished/unavailable without recorded evidence. Investigate existing logs
  before proposing separately reviewed forward-only instrumentation. Never
  backfill V2 records or retune frozen timing based on these diagnostics.

All five authority markers must remain explicitly false across plans/results;
the six immutable guards must remain present. V2 remains paper-only, read-only,
and insufficient evidence is never presented as profitability or live authority.
No Atlas, container, volume, provider, or deployment operations are performed.

## Bounded operator details

`GET /v1/intelligence/execution-v2/details` is a separate read-only diagnostic
surface. It retains the summary endpoint and frozen adequacy contract. Detail
statistics cover the latest 500 plan IDs only, explicitly marking older rows
excluded when the 501st row exists. They are not cohort adequacy statistics.
Stored registry/hash/schedule/authority evidence is validated with the canonical
worker before presentation. No worker run or evidence writes occur.

The request uses a repeatable-read, read-only transaction, a 2-second SQL statement
timeout and 5-second database-stage timeout. Source inspection covers at most
20 recorded missing-price windows, each reading at most 101 rows and exposing
at most 100 captures with truncation. Latest capture freshness uses indexed
per-mint lookups for the selected plan mints; it is not global collector health.
Each existing collector/maintenance log read is capped at 1 MB. Retained timestamp
ranges and truncation remain explicit. A window outside the retained range has
unavailable rate-limit correlation, never a manufactured zero. Correlations are
service-wide matching lines, noncausal, and not mint-specific incident counts.

Observation statistics use only bound PAPER_PRICED entry/exit clocks. Recording
delay uses terminal rows; detection receipt remains unavailable. All distributions
give sample/unavailable counts, median, nearest-rank p90 and maximum. Pending
plans stay PENDING after maturity when no terminal result exists. No P&L or
performance evaluation is added. Local heartbeats are explicitly unverified for
live process identity here, and session ends/downtime remain unavailable.
