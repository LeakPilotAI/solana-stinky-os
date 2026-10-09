"""Read-only rollback certification; never restores an old production snapshot.

Callers must fence ALL writers, resolve in-flight commands and obtain a fresh
current recovery point. A past cutover boundary cannot certify later rollback.
"""
from scripts.redis_snapshot_integrity import verify_aof_ready
from scripts.redis_stream_integrity import verify_semantic_recovery
from scripts.guarded_redis_migration import verify_no_volume_writer


def require_writer_fence(*, writers_fenced, unresolved_commands, fsync_confirmed):
    if writers_fenced is not True or type(unresolved_commands) is not int or unresolved_commands != 0:
        raise RuntimeError('Writer quiescence or in-flight acknowledgement evidence incomplete')
    if fsync_confirmed is not True:
        raise RuntimeError('Acknowledged-write durability not confirmed')


def verify_rollback_recovery(boundary, current, recovered, *, writers_fenced,
                             unresolved_commands, fsync_confirmed, persistence,
                             appendfsync, mode, recovery_window_ms=None):
    require_writer_fence(writers_fenced=writers_fenced, unresolved_commands=unresolved_commands,
                         fsync_confirmed=fsync_confirmed)
    verify_aof_ready(persistence)
    if appendfsync != 'always':raise RuntimeError('Rollback acknowledgement fsync policy unavailable')
    # The source has not restarted: BOTH current measurements must agree exactly.
    verify_semantic_recovery(boundary, current, mode='rdb')
    return verify_semantic_recovery(current, recovered, mode=mode, recovery_window_ms=recovery_window_ms)


def verify_target_storage(records, *, original_volume, source_volume, target_volume):
    if not all(isinstance(v,str) and v for v in (original_volume,source_volume,target_volume)):
        raise RuntimeError('Storage identity unavailable')
    if len({original_volume,source_volume,target_volume}) != 3:
        raise RuntimeError('Rollback requires independent storage; original volume remains intact')
    verify_no_volume_writer(records,target_volume)
