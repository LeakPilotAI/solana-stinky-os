# Reproducible paper evaluations

`POST /v1/paper/cohort-report` keeps explicit policy SHA, version, provenance
classification, timezone-aware `as_of`, and optional caller-supplied release
criteria. No criteria means evidence reporting only. Incomplete or invalid
evaluation evidence produces no artifact.

Completed PASS **and** FAIL evaluations return `evaluation_artifact_produced=true`
and `evaluation_artifact`. Its SHA-256 covers canonical UTF-8 JSON (sorted keys,
compact separators, Unicode preserved, no NaN/Infinity or type coercion):

- Schema and evaluator version; complete immutable policy provenance.
- Explicit cutoff and release criteria.
- Every selected source row, including frozen intake payload and stored payload
  digest, runtime record and computed record digest, mint, intake ID and historical
  decision/observation/persistence timestamps.
- Ordered evaluated intake IDs, chronological evidence window, metrics and result.
- Paper-only, non-activating, non-trading authority fields.

No generation timestamp enters the hash. Historical timestamps already in stored
evidence are retained. Query delivery order is normalized by creation time and
intake ID; evaluation uses close chronology with intake ID ties. A changed source
record, even an excluded open record in the selected cohort, changes the artifact.

Save the **whole returned artifact** and its digest. The offline function
`stinky_api.paper_evaluation_artifact.verify_evaluation_artifact(artifact)` checks
strict JSON, identity, supported versions, safety markers, all cohort-loader
invariants, and recomputes the evaluation. A matching digest alone is insufficient.
Unsupported versions fail closed; future semantic changes require an evaluator
version bump and retained version-specific replay code to support old artifacts.

This is a returned content-addressed snapshot, not a database evaluation ledger or
a cryptographic signature. Its content cannot change under the same verified hash.
The verifier does not prove external origin, database completeness, authenticity of
provider evidence, or empirical strategy performance. Anyone can make a different
artifact with a different hash; preserve the expected digest independently for
historical comparison. No current active policy is consulted during replay.

Persistence is deliberately unchanged: reporting remains read-only, source
evidence already has immutable intake/runtime tables, and callers can retain the
self-contained snapshot. No migration, startup DDL, policy activation, threshold
default, external RPC, or execution authority is introduced.
