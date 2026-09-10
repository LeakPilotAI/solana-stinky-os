"""Transactional persistence for the Genesis dry-run canary adapter."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
import json
from typing import Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MAX_CANARY_NOTIONAL_USD = 20.0
AUTHORITY={"interpretation":"DRY_RUN_EXECUTION_PERSISTENCE_ONLY","adapter_mode":"DRY_RUN","live_execution":False,"trading_authority":False,"trade_signal":False,"recommendation_authority":False,"rpc_contacted":False,"transaction_signed":False,"order_submitted":False,"wallet_mutated":False,"automatic_execution":False}
_CAS_SQL=text("""UPDATE canary_authorization_state SET consumed=TRUE,use_count=1,version=:proposed_version,consumed_by_attempt_id=:attempt_id,consumed_at=:consumed_at,idempotency_key=:idempotency_key,updated_at=:consumed_at WHERE authorization_id=:authorization_id AND policy_version=:policy_version AND consumed=FALSE AND use_count=0 AND version=:expected_version RETURNING authorization_id,policy_version,consumed,use_count,version""")
_AUDIT_SQL=text("""INSERT INTO dry_run_execution_audit (attempt_id,idempotency_key,authorization_id,policy_version,requested_at,requested_notional_usd,max_loss_usd,adapter_mode,authorization_version_before,authorization_version_after,authorization_transition_applied,rpc_contacted,transaction_signed,order_submitted,wallet_mutated,external_side_effects,audit_payload) VALUES (:attempt_id,:idempotency_key,:authorization_id,:policy_version,:requested_at,:requested_notional_usd,:max_loss_usd,'DRY_RUN',:expected_version,:proposed_version,TRUE,FALSE,FALSE,FALSE,FALSE,FALSE,CAST(:audit_payload AS JSONB))""")

def _unknown(missing:list[str],**extra:Any)->dict[str,Any]: return {"status":"UNKNOWN","persistence_result":"UNKNOWN","authorization_consumed_in_transaction":False,"audit_inserted_in_transaction":False,"missing":list(dict.fromkeys(missing)),**extra,**AUTHORITY}
def _blocked(blockers:list[str],**extra:Any)->dict[str,Any]: return {"status":"OBSERVED","persistence_result":"BLOCKED","authorization_consumed_in_transaction":False,"audit_inserted_in_transaction":False,"blockers":list(dict.fromkeys(blockers)),**extra,**AUTHORITY}
def _claims_external_effect(value:dict[str,Any])->bool: return any(value.get(k) is True for k in ("live_execution","trading_authority","trade_signal","recommendation_authority","rpc_contacted","transaction_signed","order_submitted","wallet_mutated","automatic_execution"))
def _dt(value:Any)->datetime|None:
    raw=str(value or "").strip()
    if not raw:return None
    try: parsed=datetime.fromisoformat(raw.replace("Z","+00:00"))
    except ValueError:return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

def _validate_prepared(prepared:dict[str,Any])->tuple[dict[str,Any]|None,dict[str,Any]|None]:
    if not isinstance(prepared,dict):return None,_unknown(["prepared_dry_run_execution"])
    if _claims_external_effect(prepared):return None,_unknown(["non_executing_dry_run_prepared_evidence"])
    missing=[]
    if prepared.get("status")!="OBSERVED":missing.append("observed_dry_run_adapter")
    if prepared.get("adapter_result")!="DRY_RUN_READY":missing.append("dry_run_adapter_ready")
    if prepared.get("dry_run_ready") is not True:missing.append("dry_run_ready")
    if prepared.get("authorization_transition_prepared") is not True:missing.append("authorization_transition_prepared")
    if str(prepared.get("adapter_mode") or "").upper()!="DRY_RUN":missing.append("dry_run_adapter_mode")
    authorization_id=str(prepared.get("authorization_id") or "").strip();attempt_id=str(prepared.get("attempt_id") or "").strip();policy_version=str(prepared.get("policy_version") or "").strip();idempotency_key=str(prepared.get("idempotency_key") or "").strip();requested_notional=prepared.get("requested_notional_usd");max_loss=prepared.get("max_loss_usd")
    if not authorization_id:missing.append("authorization_id")
    if not attempt_id:missing.append("attempt_id")
    if not policy_version:missing.append("policy_version")
    if not idempotency_key:missing.append("idempotency_key")
    if not isinstance(requested_notional,(int,float)) or isinstance(requested_notional,bool) or requested_notional<=0:missing.append("valid_requested_notional_usd")
    if not isinstance(max_loss,(int,float)) or isinstance(max_loss,bool) or max_loss<=0:missing.append("valid_max_loss_usd")
    transition=prepared.get("authorization_transition");audit=prepared.get("post_order_audit_record")
    if not isinstance(transition,dict):missing.append("authorization_transition")
    if not isinstance(audit,dict):missing.append("post_order_audit_record")
    if missing:return None,_unknown(missing,authorization_id=authorization_id or None)
    assert isinstance(transition,dict) and isinstance(audit,dict)
    expected=transition.get("expected");proposed=transition.get("proposed")
    if not isinstance(expected,dict) or not isinstance(proposed,dict):return None,_unknown(["complete_compare_and_swap_transition"],authorization_id=authorization_id)
    expected_version=expected.get("version");proposed_version=proposed.get("version");blockers=[]
    if transition.get("operation")!="COMPARE_AND_SWAP_AUTHORIZATION_CONSUMPTION":blockers.append("unexpected_transition_operation")
    if transition.get("authorization_id")!=authorization_id:blockers.append("transition_authorization_id_mismatch")
    if transition.get("must_be_atomic_before_external_side_effect") is not True:blockers.append("atomic_transition_requirement_missing")
    if transition.get("applied") is not False:blockers.append("transition_must_be_unapplied_before_persistence")
    if expected.get("consumed") is not False or expected.get("use_count")!=0:blockers.append("invalid_expected_single_use_state")
    if not isinstance(expected_version,int) or isinstance(expected_version,bool) or expected_version<0:blockers.append("invalid_expected_version")
    if proposed.get("consumed") is not True or proposed.get("use_count")!=1:blockers.append("invalid_proposed_single_use_state")
    if not isinstance(proposed_version,int) or isinstance(proposed_version,bool):blockers.append("invalid_proposed_version")
    elif isinstance(expected_version,int) and proposed_version!=expected_version+1:blockers.append("invalid_version_increment")
    if proposed.get("consumed_by_attempt_id")!=attempt_id:blockers.append("transition_attempt_id_mismatch")
    if proposed.get("idempotency_key")!=idempotency_key:blockers.append("transition_idempotency_key_mismatch")
    consumed_at=_dt(proposed.get("consumed_at"));requested_at=_dt(audit.get("requested_at"))
    if consumed_at is None:blockers.append("transition_consumed_at_missing_or_invalid")
    if requested_at is None:blockers.append("audit_requested_at_missing_or_invalid")
    if audit.get("attempt_id")!=attempt_id or audit.get("authorization_id")!=authorization_id:blockers.append("audit_identity_mismatch")
    if audit.get("policy_version")!=policy_version:blockers.append("audit_policy_version_mismatch")
    if audit.get("idempotency_key")!=idempotency_key:blockers.append("audit_idempotency_key_mismatch")
    if audit.get("adapter_mode")!="DRY_RUN":blockers.append("audit_mode_must_be_dry_run")
    if audit.get("external_side_effects") is not False:blockers.append("audit_external_side_effects_must_be_false")
    if any(audit.get(k) is not False for k in ("rpc_contacted","transaction_signed","order_submitted")):blockers.append("audit_execution_side_effects_must_be_false")
    if audit.get("authorization_transition_applied") is not False:blockers.append("prepared_audit_transition_must_be_unapplied")
    if requested_notional>MAX_CANARY_NOTIONAL_USD:blockers.append("requested_notional_exceeds_20_usd")
    if max_loss>requested_notional:blockers.append("loss_cap_exceeds_requested_notional")
    if blockers:return None,_blocked(blockers,authorization_id=authorization_id,attempt_id=attempt_id)
    assert consumed_at is not None and requested_at is not None
    return {"authorization_id":authorization_id,"attempt_id":attempt_id,"policy_version":policy_version,"idempotency_key":idempotency_key,"requested_notional_usd":float(requested_notional),"max_loss_usd":float(max_loss),"requested_at":requested_at,"consumed_at":consumed_at,"expected_version":expected_version,"proposed_version":proposed_version,"audit":deepcopy(audit)},None

async def persist_dry_run_canary_execution(session:AsyncSession,prepared:dict[str,Any])->dict[str,Any]:
    normalized,failure=_validate_prepared(prepared)
    if failure is not None:return failure
    assert normalized is not None
    params={"authorization_id":normalized["authorization_id"],"policy_version":normalized["policy_version"],"expected_version":normalized["expected_version"],"proposed_version":normalized["proposed_version"],"attempt_id":normalized["attempt_id"],"consumed_at":normalized["consumed_at"],"idempotency_key":normalized["idempotency_key"]}
    result=await session.execute(_CAS_SQL,params)
    if result.mappings().first() is None:return _blocked(["authorization_compare_and_swap_failed"],authorization_id=normalized["authorization_id"],attempt_id=normalized["attempt_id"],idempotency_key=normalized["idempotency_key"],next_step="DO_NOT_INSERT_AUDIT_OR_REPLAY_AUTHORIZATION")
    persisted_audit=deepcopy(normalized["audit"]);persisted_audit.update({"event":"CANARY_EXECUTION_ADAPTER_DRY_RUN_PERSISTED","authorization_transition_applied":True,"external_side_effects":False,"rpc_contacted":False,"transaction_signed":False,"order_submitted":False,"wallet_mutated":False,"authorization_version_before":normalized["expected_version"],"authorization_version_after":normalized["proposed_version"]})
    audit_params={**params,"requested_at":normalized["requested_at"],"requested_notional_usd":normalized["requested_notional_usd"],"max_loss_usd":normalized["max_loss_usd"],"audit_payload":json.dumps(persisted_audit,sort_keys=True,separators=(",",":"))}
    await session.execute(_AUDIT_SQL,audit_params)
    return {"status":"OBSERVED","persistence_result":"TRANSACTION_STAGED","authorization_consumed_in_transaction":True,"audit_inserted_in_transaction":True,"durable_commit_managed_by_request_session":True,"authorization_id":normalized["authorization_id"],"attempt_id":normalized["attempt_id"],"idempotency_key":normalized["idempotency_key"],"policy_version":normalized["policy_version"],"requested_notional_usd":normalized["requested_notional_usd"],"authorization_version_before":normalized["expected_version"],"authorization_version_after":normalized["proposed_version"],"authorization_transition_applied":True,"immutable_audit_staged":True,"post_order_audit_record":persisted_audit,"prepared_evidence":deepcopy(prepared),"next_step":"REQUEST_TRANSACTION_MUST_COMMIT_SUCCESSFULLY_TO_BECOME_DURABLE",**AUTHORITY}
