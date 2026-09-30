from copy import deepcopy
from unittest.mock import AsyncMock, Mock
import pytest

from stinky_api.paper_policy_identity import validated_policy_identity
from stinky_api.paper_evidence_json import content_sha256
from stinky_api.paper_policy_provisioning import _evidence_provenance, load_active_paper_configuration, validate_paper_configuration, provision_evidence_backed_paper_policy
from stinky_api.paper_runtime_worker import process_frozen_bundle, canonical_sha256
from stinky_api.prospective_paper_intake_producer import paper_configuration_from_env
from test_persistent_paper_runtime import bundle, bind_policy
from test_paper_cohort_report import row, selection, session, criteria
from stinky_api.paper_cohort_report import report_paper_cohort
from test_paper_policy_provisioning import valid_config
from test_prospective_paper_intake_producer import valid_env


def candidate_chain():
    payload = {'schema_version':'score-paper-candidate-v1', 'selected_threshold':55,
               'evaluation_as_of':'2026-09-01T00:00:00+00:00'}
    sha = canonical_sha256(payload)
    candidate = {'status':'PAPER_CANDIDATE_ARTIFACT','candidate_version':'score-paper-candidate-v1:'+sha[:16],
                 'evidence_sha256':sha,'payload':payload}
    from stinky_api.prospective_score_paper_candidate import AUTHORITY as candidate_authority
    candidate.update(candidate_authority)

    comparison = {
        'status':'OBSERVED',
        'comparison_status':'PROSPECTIVE_COMPARISON_COMPLETE',
        'candidate_version':candidate['candidate_version'],
        'evidence_sha256':sha,
        'candidate_threshold':55.0,
        'candidate_cutoff':payload['evaluation_as_of'],
        'as_of':'2026-09-02T00:00:00+00:00',
        'sample_count':2,
        'runner_count':1,
        'negative_count':1,
        'unknown_score_count':0,
        'unknown_score_rate':0.0,
        'actionable_score_count':1,
        'actionable_score_rate':1.0,
        'non_actionable_numeric_score_count':0,
        'non_actionable_numeric_score_rate':0.0,
        'score_threshold_metrics':{
            'universe':'numeric_score','eligible_count':2,'runner_count':1,'negative_count':1,
            'positive_count':1,'runner_precision':1.0,'false_discovery_rate':0.0,
            'false_positive_rate':0.0,'runner_recall':1.0,'missed_runner_count':0,
        },
        'actionable_score_threshold_metrics':{
            'universe':'actionable_score','eligible_count':2,'runner_count':1,'negative_count':1,
            'positive_count':1,'runner_precision':1.0,'false_discovery_rate':0.0,
            'false_positive_rate':0.0,'runner_recall':1.0,'missed_runner_count':0,
        },
        'actual_alert_admission_metrics':{
            'universe':'all_labeled','eligible_count':2,'runner_count':1,'negative_count':1,
            'positive_count':1,'runner_precision':1.0,'false_discovery_rate':0.0,
            'false_positive_rate':0.0,'runner_recall':1.0,'missed_runner_count':0,
        },
        'missing':[],
    }
    from stinky_api.prospective_score_candidate_readiness import assess_post_candidate_readiness
    readiness = assess_post_candidate_readiness(
        comparison,
        min_later_sample=2,
        min_later_runners=1,
        min_later_negatives=1,
        min_actionable_score_rate=1.0,
        min_actionable_positive_count=1,
        min_actionable_runner_precision=1.0,
        max_actionable_false_discovery_rate=0.0,
        max_actionable_false_positive_rate=1.0,
        min_actionable_runner_recall=1.0,
        max_actionable_missed_runners=0,
    )
    return candidate, readiness

@pytest.mark.parametrize('change',['candidate_payload','candidate_sha','version','schema','cutoff','naive','same_time','earlier','nonfinite','empty_criteria'])
def test_provisioning_rejects_malformed_or_swapped_candidate_chain(change):
    candidate, readiness = candidate_chain()
    assert _evidence_provenance(candidate,readiness) is not None
    if change=='candidate_payload': candidate['payload']['selected_threshold']=99
    if change=='candidate_sha': candidate['evidence_sha256']='z'*64
    if change=='version': candidate['candidate_version']='invented'
    if change=='schema':
        candidate['payload']['schema_version']='unsupported'
        candidate['evidence_sha256']=canonical_sha256(candidate['payload'])
        candidate['candidate_version']='unsupported:'+candidate['evidence_sha256'][:16]
        readiness.update(candidate_version=candidate['candidate_version'],evidence_sha256=candidate['evidence_sha256'])
    if change=='cutoff': readiness['comparison_as_of']='yesterday'
    if change=='naive': readiness['comparison_as_of']='2026-09-02'
    if change=='same_time': readiness['comparison_as_of']=readiness['candidate_cutoff']
    if change=='earlier': readiness['comparison_as_of']='2026-08-31T00:00:00Z'
    if change=='nonfinite': readiness['criteria']['min_later_sample']=float('inf')
    if change=='empty_criteria': readiness['criteria']={}
    assert _evidence_provenance(candidate,readiness) is None


@pytest.mark.asyncio
async def test_invalid_candidate_provisioning_does_not_touch_database():
    candidate, readiness = candidate_chain()
    candidate['payload']['selected_threshold']=99
    db=Mock(execute=AsyncMock(),commit=AsyncMock())
    result=await provision_evidence_backed_paper_policy(db,valid_config(),candidate=candidate,readiness=readiness)
    assert result['status']=='BLOCKED'
    db.execute.assert_not_awaited(); db.commit.assert_not_awaited()


@pytest.mark.parametrize('change',['missing','hash','cutoff','criteria','nonfinite','comparison_missing','comparison_format'])
def test_evidence_backed_identity_requires_complete_intact_provenance(change):
    identity=row(backed=True)['record']['policy_identity']
    assert validated_policy_identity(identity) is not None
    if change=='missing': identity['provenance']={'mode':'EVIDENCE_BACKED_SCORE_CANDIDATE','evidence_backed':True}
    if change=='hash': identity['provenance']['provenance_sha256']='0'*64
    if change=='cutoff': identity['provenance']['candidate_cutoff']='later'
    if change=='criteria': identity['provenance']['readiness_criteria']['min_later_sample']=999
    if change=='nonfinite': identity['provenance']['extra']=float('nan')
    if change=='comparison_missing':
        identity['provenance'].pop('comparison_evidence_sha256')
        body={k:v for k,v in identity['provenance'].items() if k!='provenance_sha256'}
        identity['provenance']['provenance_sha256']=content_sha256(body)
    if change=='comparison_format':
        identity['provenance']['comparison_evidence_sha256']='z'*64
        body={k:v for k,v in identity['provenance'].items() if k!='provenance_sha256'}
        identity['provenance']['provenance_sha256']=content_sha256(body)
    assert validated_policy_identity(identity) is None


@pytest.mark.parametrize('change',['threshold','assumptions','notional','version','provenance'])
def test_frozen_configuration_cannot_change_under_existing_registry_hash(change):
    payload=bundle()
    if change=='threshold': payload['paper_policy']['min_runner_probability']=.9
    if change=='assumptions': payload['execution_assumptions']['latency_ms']=1000
    if change=='notional': payload['paper_notional_usd']=10
    if change=='version': payload['paper_policy']['policy_version']='swapped'
    if change=='provenance': payload['policy_identity']['provenance']['note']='swapped'
    assert process_frozen_bundle(payload)['missing']==['frozen_policy_hash_mismatch']
    bind_policy(payload)
    assert process_frozen_bundle(payload)['status']=='OBSERVED'


@pytest.mark.parametrize('value',['z'*64,'a'*64])
def test_producer_rejects_invalid_or_swapped_registry_sha(value):
    env=valid_env(); env['STINKY_PAPER_POLICY_SHA256']=value
    assert paper_configuration_from_env(env)['configured'] is False


@pytest.mark.asyncio
async def test_loader_cannot_certify_rehashed_intake_with_changed_policy_under_old_sha():
    value=row()
    value['payload']['paper_policy']['min_runner_probability']=.9
    value['payload_sha256']=canonical_sha256(value['payload'])
    report=await report_paper_cohort(session([value]),**selection(),release_criteria=criteria())
    assert report['reasons']==['frozen_policy_hash_mismatch']
    assert report['evaluation_artifact'] is None


@pytest.mark.asyncio
async def test_active_registry_rehydration_requires_bound_comparison_evidence_hash():
    candidate, readiness = candidate_chain()
    provenance = _evidence_provenance(candidate, readiness)
    assert provenance is not None and provenance['comparison_evidence_sha256']

    payload = validate_paper_configuration(valid_config())['configuration']
    payload['provenance'] = deepcopy(provenance)
    payload['provenance'].pop('comparison_evidence_sha256')
    body = {k:v for k,v in payload['provenance'].items() if k != 'provenance_sha256'}
    payload['provenance']['provenance_sha256'] = content_sha256(body)
    value = {
        'policy_payload': payload,
        'policy_sha256': content_sha256(payload),
        'policy_version': payload['paper_policy']['policy_version'],
        'activated_at': 'stored',
    }
    fetched = Mock()
    fetched.mappings.return_value.first.return_value = value
    result = await load_active_paper_configuration(Mock(execute=AsyncMock(return_value=fetched)))
    assert result['configured'] is False
    assert result['missing'] == ['active_paper_policy_integrity']


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['version','provenance','extra_payload'])
async def test_active_registry_cannot_swap_first_class_or_full_payload_identity(change):
    checked=validate_paper_configuration(valid_config())
    payload=checked['configuration']
    value={'policy_payload':payload,'policy_sha256':checked['policy_sha256'],
           'policy_version':payload['paper_policy']['policy_version'],'activated_at':'stored'}
    if change=='version': value['policy_version']='different'
    if change=='provenance': payload['provenance']['evidence_backed']=True
    if change=='extra_payload': payload['extra']='changed'
    fetched=Mock(); fetched.mappings.return_value.first.return_value=value
    result=await load_active_paper_configuration(Mock(execute=AsyncMock(return_value=fetched)))
    assert result['configured'] is False

@pytest.mark.parametrize('target',['candidate','readiness'])
@pytest.mark.parametrize('field',['live_execution','trading_authority','automatic_activation','policy_provisioning_authority'])
def test_provisioning_does_not_launder_authority_contamination(target,field):
    candidate, readiness = candidate_chain()
    (candidate if target=='candidate' else readiness)[field]=True
    assert _evidence_provenance(candidate,readiness) is None
