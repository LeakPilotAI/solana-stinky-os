import copy
import io
import tarfile

import pytest

from scripts.genesis_saved_state_audit import REDIS_ID, VOLUME, copy_tar_artifact, verify_source


def source():
    return {'Id': REDIS_ID, 'Name': '/stinky-redis', 'State': {'Status': 'exited'},
            'Config': {'Labels': {'com.docker.compose.project': 'project-genesis',
                                  'com.docker.compose.service': 'redis'}},
            'Mounts': [{'Type': 'volume', 'Name': VOLUME, 'Destination': '/data', 'RW': True}]}


@pytest.mark.parametrize('case', ['ok', 'id', 'name', 'running', 'project', 'volume', 'readonly', 'shared_writer', 'duplicate'])
def test_export_requires_pinned_stopped_owned_storage(case):
    row = source(); rows = [row]
    if case == 'id': row['Id'] = 'other'
    if case == 'name': row['Name'] = '/atlas-redis'
    if case == 'running': row['State']['Status'] = 'running'
    if case == 'project': row['Config']['Labels']['com.docker.compose.project'] = 'atlas'
    if case == 'volume': row['Mounts'][0]['Name'] = 'other'
    if case == 'readonly': row['Mounts'][0]['RW'] = False
    if case == 'shared_writer':
        other = copy.deepcopy(row); other['Id'] = 'test'; other['State']['Status'] = 'running'; rows.append(other)
    if case == 'duplicate': rows.append(copy.deepcopy(row))
    if case == 'ok': assert verify_source(rows) == row
    else:
        with pytest.raises(ValueError): verify_source(rows)


def archive(name='dump.rdb', kind=tarfile.REGTYPE, payload=b'REDIS0012' + b'x' * 20, duplicate=False):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as tar:
        for _ in range(2 if duplicate else 1):
            info = tarfile.TarInfo(name); info.type = kind; info.size = len(payload) if kind == tarfile.REGTYPE else 0
            tar.addfile(info, io.BytesIO(payload))
    stream.seek(0)
    return stream


def test_copy_is_bounded_exclusive_and_does_not_claim_checksum(tmp_path):
    target = tmp_path / 'protected.rdb'
    manifest = copy_tar_artifact(archive(), target)
    assert manifest['bytes'] == 29 and not manifest['checksum_verified']
    original = target.read_bytes()
    with pytest.raises(FileExistsError): copy_tar_artifact(archive(), target)
    assert target.read_bytes() == original


@pytest.mark.parametrize('case', ['traversal', 'symlink', 'multiple', 'header'])
def test_malformed_exports_never_certify_recovery(tmp_path, case):
    kwargs = {}
    if case == 'traversal': kwargs['name'] = '../dump.rdb'
    if case == 'symlink': kwargs['kind'] = tarfile.SYMTYPE
    if case == 'multiple': kwargs['duplicate'] = True
    if case == 'header': kwargs['payload'] = b'invalid' * 4
    with pytest.raises(ValueError): copy_tar_artifact(archive(**kwargs), tmp_path / 'copy.rdb')


def test_oversized_tar_member_rejected_before_destination_creation(tmp_path):
    from scripts.redis_snapshot_integrity import MAX_SNAPSHOT_BYTES
    member = tarfile.TarInfo('dump.rdb'); member.size = MAX_SNAPSHOT_BYTES + 1
    stream = io.BytesIO(member.tobuf() + b'\0' * 1024)
    target = tmp_path / 'oversized.rdb'
    with pytest.raises(ValueError): copy_tar_artifact(stream, target)
    assert not target.exists()
