# Immutable paper cohort reporting

`POST /v1/paper/cohort-report` is read-only. It requires explicit
`policy_sha256` (64 lowercase hex characters), `policy_version`,
`evidence_backed` (a JSON boolean), and a timezone-aware `as_of`.
It never reads the active-policy pointer or uses all-policy aggregate counts.

Example request (substitute an actual stored identity):

```json
{
  "policy_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "policy_version": "operator-supplied-version",
  "evidence_backed": false,
  "as_of": "2026-09-30T12:00:00Z",
  "record_limit": 500
}
```

Without `release_criteria`, the response reports evidence state and does not
evaluate or manufacture release thresholds. To request evaluation, supply all
four existing walk-forward criteria: `minimum_closed_trades`,
`minimum_mean_net_return_pct`, `maximum_drawdown_pct`, `minimum_win_rate`.
Empty or malformed criteria yield UNKNOWN evaluation. A passing manual cohort
remains manual (`evidence_backed=false`); evaluation never activates any policy
or grants execution authority.

The loader reads at most `record_limit + 1` rows under the selected SHA and
persistence cutoff. The default 500 and maximum 2000 are resource limits, not
sample requirements. Overflow returns UNKNOWN with no evaluation or partial
performance claim. Increase the explicit limit within the cap if appropriate;
cohorts exceeding the cap require a separately designed bounded export path.
Migration 014 adds the matching SHA/creation-time/intake-ID index; no startup DDL
or historical identity backfill is added.

Every selected record must agree with its first-class identity, full stored
provenance, and hash-verified frozen intake. Missing/legacy identity stays
UNKNOWN. Close time comes from stored `paper_close_evidence.captured_at`, must
match intake observation time, and must be later than T0 and no later than
intake/record persistence and the requested cutoff. Missing chronology is never
replaced with processing time. Closed simulations go through the existing
adapter and evaluator in deterministic close-time/intake-ID order. Duplicate
record IDs or repeated closed simulations for the same mint/T0 fail closed.

Counts are immutable record counts: an open simulation record remains historical
after a separate close record arrives. `open_simulation_records` is **not** a
count of currently open positions. Unprocessed intake has no immutable runtime
identity yet and is not included. The report does not claim an intake queue count.

Command Center labels existing totals as all-policy observability and provides
an on-demand explicit cohort inspection. It displays full SHA/version/provenance,
closed sample and chronology, structural eligibility, and that no criteria were
supplied or walk-forward evaluation performed. The API accepts explicit criteria
for evaluation; the inspection UI intentionally reports evidence state only.

Code/test verification does not establish real sample sufficiency, profitability,
formal paper validation, or endurance readiness. Long-duration soak remains deferred.
