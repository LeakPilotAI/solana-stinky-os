# Genesis Docker evidence retention

Checkpoint61 audit was strictly read-only: no lifecycle, cleanup, volume or data
operation. Its full local inventory is
`logs/checkpoint61-continuation-docker-inventory.json`, containing names, full IDs,
creation/start times, Compose/certification labels, image identities, port bindings,
mounts, volume references/labels and resource limits. Raw environment variables and
credential-bearing commands are excluded.

The audit found83 containers and67 volumes across the host. Final classification:
three Genesis production dependencies,72 retained checkpoint/test containers,
two potential container-only cleanup candidates and six unrelated containers.
The candidates are the stopped MinIO initialization utility and never-started
failed-bind fixture; their original classifications remain in the manifest.
49 volumes have Genesis names. All73 test/evidence fixtures were stopped or never
started; none had
writable production Redis storage. Stopped containers have no running Redis CPU or
resident process workload, but still retain filesystem layers, volumes and metadata.
Actual disk bytes were not measured; configured memory limits are not memory use.

The five `genesis-checkpoint` containers are checkpoint54 RDB/durable/config proofs
and checkpoint57 AOF/RDB proofs. Their bind mounts point to separate local test
directories, not production storage. The initialization utility's Compose project,
working directory and `minio-init` service labels establish Genesis ownership; it
is not an unknown application or a fourth production dependency.

## Immediate holds

Preserve production dependencies and volumes, the original Redis/rollback storage,
protected RDB copies and their manifests, frozen evidence, the V2 test database,
unique failure evidence and latest representative positive/recovery/HOLD proofs.
Do not treat an old snapshot as current production recovery evidence. Keep the
unregistered-write HOLD fixture and its current candidate storage until its proof
is independently archived and verified. Atlas and unrelated resources are excluded.

There is no cleanup authorization in checkpoint61. “Potential cleanup candidate”
means future review eligibility, not permission. The stopped MinIO initialization
utility and never-started failed-bind fixture are candidates for container-only
review; their volume/data dependencies must still be checked separately. No volume
is approved for removal by this policy.

## Bound future accumulation

The current accumulation exceeds the retention budget: freeze creation of additional
fixture generations unless a new defect cannot be certified with retained evidence
and the proposed fixture budget is recorded first. Serialize tests sharing ports.
Future checkpoints should use at most four active fixtures and eight newly retained
containers; reaching either limit requires stopping fixture creation and documenting
why more evidence is necessary. These are admission budgets, never deletion triggers.
Do not overwrite old fixture datasets to avoid a budget; reuse is allowed only when
the operation preserves its evidence and exact ownership/storage isolation is proven.

At each checkpoint closure, assign every fixture an owner, purpose, checkpoint,
related proof/snapshot paths, checksum manifest, storage references and retention hold.
Review obsolete duplicates and failed empty preparations after30 days, or sooner
when the replacement proof is certified. Keep one representative positive, negative
and HOLD/recovery fixture per distinct behavior until verified exports independently
preserve all necessary evidence. Critical production rollback holds take precedence.

## Eventual cleanup requires separate authorization

Prepare a concrete manifest listing exact container/volume IDs, ownership, stopped
state, all mount references, unique contents, replacement archive checksums and an
independent restore proof. Verify no shared production/Atlas/test-database storage
and no active writer. Obtain explicit approval for that exact manifest before any
removal. Container retirement and volume/data retirement are separate decisions.
Unknown ownership or an unverified archive blocks cleanup. Never use broad prune,
Compose-down, volume deletion, directory deletion or age alone as cleanup authority.

This policy bounds new accumulation even when cleanup approval is absent. It does
not schedule automatic cleanup, claim that archives have already been exported,
or modify any existing container, volume, snapshot or canonical continuity file.
