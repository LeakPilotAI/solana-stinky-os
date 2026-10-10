from types import SimpleNamespace
import pytest
from scripts.redis_broker_recovery import expose_readonly_after_quarantined_load
from stinky_core.transport.redis_accounting import AccountingError


def client():
    actions=[]
    policy={'flags':['off'],'passwords':[],'categories':['-@all'],'selectors':[],
            'commands':['+xclaim','+xgroup|setid']}
    c=SimpleNamespace(policy=policy,port='0',loading=0,actions=actions,reply=[True,True,True])
    c.config_get=lambda name:{'port':c.port}
    c.info=lambda name:{'loading':c.loading}
    c.acl_getuser=lambda name:c.policy
    pipe=SimpleNamespace(execute_command=lambda *args:actions.append(args),execute=lambda:c.reply)
    c.pipeline=lambda transaction:pipe
    return c


def test_loader_exposure_atomically_fences_default_and_bootstrap_without_writer_grant():
    c=client();scopes=[]
    result=expose_readonly_after_quarantined_load(c,verify_scope=lambda:scopes.append(True),bootstrap_user='bootstrap')
    assert len(scopes)==2 and result=={'state':'READ_ONLY_VERIFICATION_REQUIRED','writers_authorized':False}
    assert c.actions[0][:5]==('ACL','SETUSER','default','off','resetpass')
    assert c.actions[1]==('CONFIG','SET','port','6379')
    assert c.actions[2]==('ACL','SETUSER','bootstrap','off','resetpass','-@all')


@pytest.mark.parametrize('fault',['exposed_tcp','loading','default_on','nopass','broad_commands','selector','password'])
def test_unquarantined_or_unsafe_load_never_exposes_endpoint(fault):
    c=client()
    if fault=='exposed_tcp':c.port='6379'
    elif fault=='loading':c.loading=1
    elif fault=='default_on':c.policy['flags']=['on']
    elif fault=='nopass':c.policy['flags'].append('nopass')
    elif fault=='broad_commands':c.policy['commands'].append('+set')
    elif fault=='selector':c.policy['selectors']=[{'commands':'+@all'}]
    else:c.policy['passwords']=['hash']
    with pytest.raises(AccountingError):expose_readonly_after_quarantined_load(c,verify_scope=lambda:None,bootstrap_user='bootstrap')
    assert not c.actions


def test_partial_transition_is_not_reported_verified():
    c=client();c.reply=[True,False,True]
    with pytest.raises(AccountingError):expose_readonly_after_quarantined_load(c,verify_scope=lambda:None,bootstrap_user='bootstrap')


def test_scope_failure_precedes_any_configuration_operation():
    c=client()
    def fail():raise AccountingError('unowned')
    with pytest.raises(AccountingError):expose_readonly_after_quarantined_load(c,verify_scope=fail,bootstrap_user='bootstrap')
    assert not c.actions
