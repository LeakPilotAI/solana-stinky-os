from copy import deepcopy
import json

import pytest

from stinky_api.paper_cohort_report import report_paper_cohort
from stinky_api.paper_evaluation_artifact import content_sha256, verify_evaluation_artifact
from stinky_api.paper_runtime_worker import canonical_sha256, process_frozen_bundle
from test_paper_cohort_report import criteria, row, selection, session
from test_persistent_paper_runtime import bind_policy


async def artifact(rows=None, **kwargs):
    report = await report_paper_cohort(session(rows if rows is not None else [row()]),
                                     **selection(), release_criteria=criteria(), **kwargs)
    assert report['evaluation_artifact_produced'] is True
    return report['evaluation_artifact']


def second_row():
    value = row('close-2', at='2026-09-10T09:00:00Z')
    value['mint'] = value['intake_mint'] = value['payload']['decision_context']['mint'] = 'mint-2'
    value['payload_sha256'] = canonical_sha256(value['payload'])
    value['record'] = process_frozen_bundle(value['payload'])
    return value


@pytest.mark.asyncio
async def test_exact_sources_reproduce_offline_after_json_roundtrip_and_active_policy_change(monkeypatch):
    rows = [row(), second_row()]
    original = await artifact(rows)
    monkeypatch.setenv('STINKY_PAPER_POLICY_VERSION', 'unrelated-active-policy')
    monkeypatch.setenv('STINKY_PAPER_POLICY_SHA256', 'b' * 64)
    assert await artifact(deepcopy(rows)) == original
    # Query delivery order is not the evaluation order: timestamps + intake IDs are.
    assert await artifact(list(reversed(rows))) == original
    assert verify_evaluation_artifact(json.loads(json.dumps(original)))['valid'] is True
    assert original['content']['evaluated_intake_ids'] == ['close-1', 'close-2']
    assert 'generated_at' not in original['content']


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['cutoff', 'criteria', 'records', 'payload', 'policy_sha', 'policy_version', 'provenance'])
async def test_material_input_changes_identity(change):
    values = [row()]
    first = await artifact(values)
    args = selection()
    policy = criteria()
    if change == 'cutoff': args['as_of'] = '2026-09-12T00:00:00Z'
    if change == 'criteria': policy['minimum_win_rate'] = 0.5
    if change == 'records': values.append(second_row())
    if change == 'payload': values[0]['payload']['additional_evidence'] = {'source': 'different'}
    if change == 'policy_sha':
        args['policy_sha256'] = 'b' * 64
        values[0]['policy_sha256'] = 'b' * 64
        values[0]['payload']['policy_identity']['policy_sha256'] = 'b' * 64
    if change == 'policy_version':
        args['policy_version'] = 'different-version'
        values[0]['policy_version'] = 'different-version'
        values[0]['payload']['paper_policy']['policy_version'] = 'different-version'
    if change == 'provenance':
        values[0]['payload']['policy_identity']['provenance']['operator_note'] = 'different'
    if change in ('payload', 'policy_sha', 'policy_version', 'provenance'):
        if change == 'policy_sha':
            report = await report_paper_cohort(session(values), **args, release_criteria=policy)
            assert not report['evaluation_artifact_produced']
            return
        bind_policy(values[0]['payload'])
        args['policy_sha256'] = values[0]['policy_sha256'] = values[0]['payload']['policy_identity']['policy_sha256']
        processed = values[0]['record']['processed_at']
        values[0]['record'] = process_frozen_bundle(values[0]['payload'])
        values[0]['record']['processed_at'] = processed
        values[0]['payload_sha256'] = canonical_sha256(values[0]['payload'])
    report = await report_paper_cohort(session(values), **args, release_criteria=policy)
    other = report['evaluation_artifact']
    assert other['artifact_sha256'] != first['artifact_sha256']
    assert verify_evaluation_artifact(other)['valid'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('rehash', [False, True])
@pytest.mark.parametrize('change', ['result', 'source_hash', 'missing_id', 'missing_payload', 'authority',
    'schema', 'evaluator', 'criteria', 'policy', 'order', 'evaluated_order', 'nan', 'bool_authority'])
async def test_tampered_or_rehashed_invalid_artifacts_fail_closed(change, rehash):
    value = await artifact([row(), second_row()])
    content = value['content']
    if change == 'result': content['evaluation']['release_gate_result'] = 'FICTION'
    if change == 'source_hash': content['source_records'][0]['record_sha256'] = '0' * 64
    if change == 'missing_id': content['source_records'][0]['intake_id'] = None
    if change == 'missing_payload': content['source_records'][0].pop('payload')
    if change == 'authority': content['authority']['automatic_activation'] = True
    if change == 'bool_authority': content['authority']['live_execution'] = 0
    if change == 'schema': content['schema_version'] = 'unknown-version'
    if change == 'evaluator': content['evaluator_version'] = 'unknown-evaluator'
    if change == 'criteria': content['release_criteria'] = None
    if change == 'policy': content['policy_identity']['policy_sha256'] = 'z' * 64
    if change == 'order': content['source_records'].reverse()
    if change == 'evaluated_order': content['evaluated_intake_ids'].reverse()
    if change == 'nan': content['evaluation']['win_rate'] = float('nan')
    if rehash and change != 'nan': value['artifact_sha256'] = content_sha256(content)
    checked = verify_evaluation_artifact(value)
    assert checked['valid'] is False
    assert checked['automatic_activation'] is checked['live_execution'] is checked['trading_authority'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('release', [None, {}, criteria(minimum_closed_trades=100)])
async def test_no_completed_evaluation_means_no_artifact(release):
    report = await report_paper_cohort(session([row()]), **selection(), release_criteria=release)
    assert report['evaluation_artifact_produced'] is False
    assert report['evaluation_artifact'] is None
    assert not report['walk_forward_evaluated']


@pytest.mark.asyncio
async def test_completed_fail_has_artifact_but_no_authority():
    report = await report_paper_cohort(session([row()]), **selection(),
                                     release_criteria=criteria(minimum_mean_net_return_pct=1e6))
    assert report['walk_forward']['release_gate_result'] == 'FAIL'
    assert report['evaluation_artifact_produced']
    assert verify_evaluation_artifact(report['evaluation_artifact'])['valid']


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['mixed', 'legacy', 'nonfinite'])
async def test_ineligible_evidence_never_gets_artifact(kind):
    values = [row()]
    if kind == 'mixed': values.append(row('second', backed=True))
    if kind == 'legacy': values[0]['policy_sha256'] = None
    if kind == 'nonfinite': values[0]['record']['additional'] = float('inf')
    report = await report_paper_cohort(session(values), **selection(), release_criteria=criteria())
    assert report['evaluation_artifact'] is None
    assert report['evaluation_artifact_produced'] is False


@pytest.mark.parametrize('value', [None, [], {}, {'content': {}}, {'content': [], 'artifact_sha256': ''}])
def test_malformed_envelope_is_unknown(value):
    assert verify_evaluation_artifact(value)['valid'] is False

@pytest.mark.asyncio
async def test_evidence_backed_artifact_preserves_complete_provenance_and_replays():
    value = row(backed=True)
    report = await report_paper_cohort(session([value]),
        **selection(policy_sha256=value['policy_sha256'], evidence_backed=True), release_criteria=criteria())
    assert report['evaluation_artifact_produced']
    artifact = report['evaluation_artifact']
    assert artifact['content']['policy_identity']['provenance']['evidence_backed'] is True
    assert verify_evaluation_artifact(artifact)['valid'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('field', ['automatic_activation','wallet_mutated','recommendation_authority'])
async def test_contaminated_source_authority_is_rejected_even_with_recomputed_hashes(field):
    original = await artifact()
    source = original['content']['source_records'][0]
    source['record'][field] = True
    source['record_sha256'] = content_sha256(source['record'])
    original['artifact_sha256'] = content_sha256(original['content'])
    assert verify_evaluation_artifact(original)['valid'] is False


@pytest.mark.asyncio
async def test_artifact_is_detached_from_later_caller_mutations():
    values = [row()]
    result = await artifact(values)
    original = deepcopy(result)
    values[0]['payload']['decision_context']['mint'] = 'mutated'
    values[0]['record']['policy_identity']['policy_version'] = 'mutated'
    assert result == original
    assert verify_evaluation_artifact(result)['valid'] is True


@pytest.mark.asyncio
async def test_verification_route_preserves_offline_non_authoritative_semantics():
    from stinky_api.paper_cohort_routes import paper_evaluation_artifact_verify
    value = await artifact()
    checked = await paper_evaluation_artifact_verify({"artifact": value})
    assert checked["status"] == "VERIFIED"
    assert checked["valid"] is True
    assert checked["automatic_activation"] is False
    assert checked["live_execution"] is False
    assert checked["trading_authority"] is False
    invalid = await paper_evaluation_artifact_verify({"artifact": {"artifact_sha256": "0" * 64, "content": {}}})
    assert invalid["valid"] is False
    assert invalid["automatic_activation"] is False
