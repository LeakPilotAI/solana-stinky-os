"""Entity resolver service – batch + event-driven entity intelligence."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import redis.asyncio as redis
import structlog

from entity_resolver.behavior import BehaviorFingerprintStore
from entity_resolver.config import settings
from entity_resolver.launch_history import LaunchHistoryStore
from entity_resolver.relationships import WalletRelationshipStore
from entity_resolver.resolver import EntityResolver
from entity_resolver.store import EntityStore

logger = structlog.get_logger(__name__)


class EntityService:
    def __init__(self) -> None:
        self._store = EntityStore()
        self._launch_history = LaunchHistoryStore()
        self._behavior = BehaviorFingerprintStore()
        self._relationships = WalletRelationshipStore()
        self._resolver = EntityResolver(self._store)
        self._redis: redis.Redis | None = None
        self._running = False

    async def start(self) -> None:
        await self._store.ensure_schema()
        await self._launch_history.ensure_schema()
        await self._behavior.ensure_schema()
        await self._relationships.ensure_schema()
        self._redis = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=10,
            retry_on_timeout=False,
            health_check_interval=30,
            socket_keepalive=True,
        )
        try:
            await self._redis.xgroup_create(
                settings.event_stream,
                settings.entity_consumer_group,
                id="0",
                mkstream=True,
            )
        except Exception:
            pass
        self._running = True
        logger.info(
            "entity_service.started",
            stream=settings.event_stream,
            group=settings.entity_consumer_group,
        )
        await self._resolver.run_batch()

    async def stop(self) -> None:
        self._running = False
        if self._redis:
            await self._redis.aclose()
        await self._behavior.close()
        await self._launch_history.close()
        await self._resolver.close()
        await self._relationships.close()

    async def run_forever(self) -> None:
        await self.start()
        assert self._redis is not None
        consumer = f"entity-{id(self)}"
        last_batch = asyncio.get_event_loop().time()
        backoff = 1.0
        while self._running:
            try:
                rows = await self._redis.xreadgroup(
                    groupname=settings.entity_consumer_group,
                    consumername=consumer,
                    streams={settings.event_stream: ">"},
                    count=20,
                    block=5000,
                )
                backoff = 1.0
                if rows:
                    for _stream, messages in rows:
                        for msg_id, fields in messages:
                            await self._handle(msg_id, fields)

                now = asyncio.get_event_loop().time()
                if now - last_batch >= settings.batch_interval_sec:
                    await self._resolver.run_batch()
                    last_batch = now
            except Exception as exc:
                logger.warning("entity_service.loop_error", error=str(exc)[:240], backoff=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    @staticmethod
    def _event_timestamp(event: dict[str, object]) -> datetime:
        payload = event.get("payload") or {}
        value = event.get("occurred_at") or event.get("observed_at")
        if isinstance(payload, dict):
            value = value or payload.get("occurred_at") or payload.get("observed_at")
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        if isinstance(value, str) and value.strip():
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc)

    @staticmethod
    def _outcome_payload(event: dict[str, object]) -> tuple[str | None, str | None, dict[str, object]]:
        """Extract measured completion evidence from the canonical event."""
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            return None, None, {}
        mint = payload.get("mint")
        if not isinstance(mint, str) or not mint:
            return None, None, {}
        status = payload.get("outcome_status") or payload.get("status") or payload.get("outcome")
        if not isinstance(status, str) or not status:
            if event.get("event_type") == "post_migration.tracking_completed":
                status = "completed"
            else:
                return mint, None, {}
        metadata = {k: v for k, v in payload.items() if k != "mint"}
        return mint, status, metadata

    @staticmethod
    def _funding_payload(event: dict[str, object]) -> tuple[str, str, datetime, int | None, str | None, dict[str, object]] | None:
        """Extract only explicitly identified native-SOL transfer evidence.

        Missing asset identity is rejected rather than guessing that a generic
        token transfer is funding. No ownership or intent is inferred.
        """
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            return None
        asset_type = str(payload.get("asset_type") or payload.get("asset") or "").strip().lower()
        if asset_type not in {"sol", "native_sol", "native"}:
            return None

        source = payload.get("source_wallet") or payload.get("from_wallet") or payload.get("from")
        destination = payload.get("destination_wallet") or payload.get("to_wallet") or payload.get("to")
        if not isinstance(source, str) or not source or not isinstance(destination, str) or not destination:
            return None
        if source == destination:
            return None

        amount = payload.get("amount_lamports")
        if amount is None:
            amount = payload.get("lamports")
        try:
            amount_lamports = int(amount) if amount is not None else None
        except (TypeError, ValueError):
            return None
        if amount_lamports is not None and amount_lamports < 0:
            return None

        signature = event.get("signature") or payload.get("signature")
        signature = str(signature) if signature else None
        observed_at = EntityService._event_timestamp(event)
        evidence = {
            "event_type": event.get("event_type"),
            "event_id": event.get("event_id"),
            "slot": event.get("slot"),
            "asset_type": asset_type,
            "evidence_basis": "canonical_token_transfer_event",
        }
        return source, destination, observed_at, amount_lamports, signature, evidence

    async def _handle(self, msg_id: str, fields: dict[str, str]) -> None:
        """Process one stream event and ACK only after successful processing."""
        assert self._redis is not None

        raw = fields.get("data") or fields.get("payload") or ""
        if not raw:
            for value in fields.values():
                if isinstance(value, str) and value.startswith("{"):
                    raw = value
                    break

        if not raw:
            raise ValueError(f"event {msg_id} has no JSON payload")

        event = json.loads(raw)
        et = event.get("event_type") or event.get("type")
        payload = event.get("payload") or {}

        if et == "token.launch":
            deployer = payload.get("deployer")
            if deployer:
                entity_id = await self._resolver.ensure_deployer_observed(deployer)
                mint = payload.get("mint") or payload.get("token") or payload.get("address")
                inserted = await self._launch_history.record_launch(
                    entity_id=entity_id,
                    deployer_wallet=deployer,
                    event_id=msg_id,
                    mint=mint,
                    observed_at=self._event_timestamp(event),
                )
                if inserted:
                    fingerprint = await self._behavior.refresh_entity(entity_id)
                    logger.info(
                        "entity.launch_recorded",
                        entity_id=entity_id,
                        deployer=deployer,
                        mint=mint,
                        cadence_bucket=fingerprint["cadence_bucket"],
                    )
                else:
                    logger.debug("entity.launch_duplicate", event_id=msg_id, deployer=deployer, mint=mint)

        elif et == "token.migrated":
            creator = payload.get("creator") or payload.get("deployer")
            if creator:
                await self._resolver.ensure_deployer_observed(creator)

        elif et == "post_migration.tracking_completed":
            mint, status, metadata = self._outcome_payload(event)
            if mint and status:
                updated = await self._launch_history.record_outcome(
                    mint=mint,
                    status=status,
                    metadata=metadata,
                    observed_at=self._event_timestamp(event),
                )
                if updated:
                    fingerprint = await self._behavior.refresh_for_mint(mint)
                    logger.info(
                        "entity.launch_outcome_recorded",
                        mint=mint,
                        status=status,
                        cadence_bucket=(fingerprint or {}).get("cadence_bucket"),
                    )

        elif et == "token.transfer":
            funding = self._funding_payload(event)
            if funding:
                source, destination, observed_at, amount_lamports, signature, evidence = funding
                await self._relationships.record_funding_observation(
                    source_wallet=source,
                    destination_wallet=destination,
                    observed_at=observed_at,
                    amount_lamports=amount_lamports,
                    signature=signature,
                    evidence=evidence,
                )
                logger.debug(
                    "entity.funding_observed",
                    source=source,
                    destination=destination,
                    amount_lamports=amount_lamports,
                    signature=signature,
                )

        await self._redis.xack(
            settings.event_stream,
            settings.entity_consumer_group,
            msg_id,
        )
