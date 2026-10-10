import copy

import pytest

from scripts.redis_writer_broker import PinnedRedisScope
from stinky_core.transport.redis_accounting import AccountingError


def record():
    return {'Id': 'a' * 64, 'Image': 'sha256:' + 'b' * 64, 'Name': '/genesis-redis-c68-fixture',
            'Config': {'Labels': {'com.docker.compose.project': 'project-genesis',
                                  'com.docker.compose.service': 'redis',
                                  'genesis.certification': 'checkpoint68'}},
            'Mounts': [{'Type': 'volume', 'Name': 'project-genesis_checkpoint68-fixture',
                        'Destination': '/data', 'RW': True}],
            'HostConfig': {'PortBindings': {'6379/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '16574'}]}},
            'State': {'Running': True, 'Paused': False}}


def pin():
    return PinnedRedisScope(container_id='a' * 64, image='sha256:' + 'b' * 64,
                            name='genesis-redis-c68-fixture', volume='project-genesis_checkpoint68-fixture',
                            port=16574, certification='checkpoint68')


def test_exact_new_checkpoint_scope_and_loopback_binding():
    pin()([record()])


@pytest.mark.parametrize('address', ['', '0.0.0.0', '::', '192.168.1.1', 'localhost'])
def test_nonexplicit_loopback_bindings_rejected(address):
    observed = record(); observed['HostConfig']['PortBindings']['6379/tcp'][0]['HostIp'] = address
    with pytest.raises(AccountingError):
        pin()([observed])


def test_extra_wildcard_mapping_cannot_be_hidden_by_loopback_mapping():
    observed = record()
    observed['HostConfig']['PortBindings']['6379/tcp'].append({'HostIp': '', 'HostPort': '16574'})
    with pytest.raises(AccountingError):
        pin()([observed])


@pytest.mark.parametrize('change', ['production_volume', 'wrong_checkpoint', 'different_id', 'different_port'])
def test_loopback_does_not_override_native_storage_or_identity_ownership(change):
    observed = copy.deepcopy(record())
    if change == 'production_volume':
        observed['Mounts'][0]['Name'] = 'project-genesis_redis-data'
    elif change == 'wrong_checkpoint':
        observed['Config']['Labels']['genesis.certification'] = 'checkpoint67'
    elif change == 'different_id':
        observed['Id'] = 'c' * 64
    else:
        observed['HostConfig']['PortBindings']['6379/tcp'][0]['HostPort'] = '6380'
    with pytest.raises(AccountingError):
        pin()([observed])
