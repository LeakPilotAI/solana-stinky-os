"""Authoritative global-fee resolver.

NEVER approximates fees from volume, liquidity, mcap, or a guessed bps.
NEVER treats creator-only fields as global_fees_sol.
UNKNOWN observations are optional evidence — they do NOT fail Gate 1
on the volume-first profile.

Sources (in order), all explicit:
  1. Public API fields that are actually named fees (pump.fun coin JSON)
  2. On-chain SOL/WSOL received by published pump.fun protocol fee recipients
     (lower bound of protocol fees; sufficient to PASS if >= 1 SOL)

Creator-vault balances are per-creator unclaimed remainder, not per-mint
all-time fees — they are not used.

Resolver version: fee-resolver-v1.0.0
"""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable, Iterable, Mapping

RESOLVER_VERSION = "fee-resolver-v1.0.0"
WSOL_MINT = "So11111111111111111111111111111111111111112"
PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_AMM_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
PUMP_FEE_PROGRAM = "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ"
PUMP_V2_TRADES = "https://swap-api.pump.fun/v2/coins/{mint}/trades"
PUMP_COIN_V3 = "https://frontend-api-v3.pump.fun/coins/{mint}"

# Protocols whose fee recipients we can identify on-chain.
PUMP_FAMILY: frozenset[str] = frozenset(
    {"pump", "pumpfun", "pumpswap", "pump.fun", "mayhem"}
)

# Published pump.fun protocol fee recipients (bonding curve + AMM).
# Classic Global.feeRecipient set + 2025 8-recipient rotation.
PROTOCOL_FEE_RECIPIENTS: frozenset[str] = frozenset(
    {
        "CebN5WGQ4jvEPvsVU4EoHEpgzq1VV7AbicfhtW4xC9iM",
        "62qc2CNXwrYqQScmEdiZFFAnJR262PxWEuNQtxfafNgV",
        "FWsW1xNtWscwNmKv6wVsU1iTzRN6wmmk3MjxRP5tT7hz",
        "9rPYyANsfQZw3DnDmKE3YCQF5E8oD89UXoHn9JFEhJUz",
        "5YxQFdt3Tr9zJLvkFccqXVUwhdTWJQc1fFg2YPbxvxeD",
        "9M4giFFMxmFGXtc3feFzRai56WbBqehoSeRE5GK7gf7",
        "GXPFM2caqTtQYC2cJ5yJRi9VDkpsYZXzYdwYpGnLmtDL",
        "3BpXnfJaUTiwXnJNe7Ej1rcbzqTTQUvLShZaWazebsVR",
        "5cjcW9wExnJJiqgLjq7DEG75Pm6JBgE1hNv4B2vHXUW6",
        "EHAAiTxcdDwQ3U4bU6YcMsQGaekdzLS3B5SmYo46kJtL",
        "5eHhjP8JaYkz83CWwvGU2uMUXefd3AazWGx4gpcuEEYD",
        "A7hAgCzFw14fejgCp387JUJRMNyz4j89JKnhtKU8piqW",
    }
)

# Explicit fee field names. creator_fees_* is NOT global fees.
EXPLICIT_FEE_KEYS: tuple[str, ...] = (
    "total_fees",
    "total_fees_sol",
    "fees_sol",
    "fee_sol",
    "global_fees_paid",
    "global_fees_sol",
    "accumulated_fees",
)

DEFAULT_RPC_URLS: tuple[str, ...] = (
    "https://solana-rpc.publicnode.com",
    "https://api.mainnet-beta.solana.com",
)

DEFAULT_MAX_AGE_SEC = 300.0
DEFAULT_CACHE_TTL_SEC = 60.0
DEFAULT_MAX_TXS = 80
DEFAULT_TRADE_PAGES = 12
DEFAULT_PASS_THRESHOLD_SOL = 1.0
_HTTP_GET_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 StinkyOS/fee-resolver-v1.0.0",
}
_HTTP_RPC_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 StinkyOS/fee-resolver-v1.0.0",
    "Origin": "https://solana.com",
    "Referer": "https://solana.com/",
}

FEE_OBSERVATIONS_DDL = """
CREATE TABLE IF NOT EXISTS fee_observations (
    id BIGSERIAL PRIMARY KEY,
    mint TEXT NOT NULL,
    protocol TEXT,
    global_fees_sol DOUBLE PRECISION,
    source TEXT NOT NULL,
    verified BOOLEAN NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolver_version TEXT NOT NULL,
    fees_status TEXT NOT NULL,
    fees_error TEXT,
    fees_confidence DOUBLE PRECISION,
    scan_complete BOOLEAN,
    txs_parsed INTEGER,
    lower_bound BOOLEAN,
    raw_reference JSONB NOT NULL DEFAULT '{}'::jsonb
)
"""

FEE_OBSERVATIONS_INDEXES = (
    """
    CREATE INDEX IF NOT EXISTS idx_fee_obs_mint_observed
        ON fee_observations (mint, observed_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_fee_obs_verified
        ON fee_observations (verified, observed_at DESC)
    """,
)

FEE_OBSERVATIONS_INSERT = """
INSERT INTO fee_observations (
    mint, protocol, global_fees_sol, source, verified,
    observed_at, resolver_version, fees_status, fees_error,
    fees_confidence, scan_complete, txs_parsed, lower_bound, raw_reference
) VALUES (
    :mint, :protocol, :global_fees_sol, :source, :verified,
    CAST(:observed_at AS timestamptz), :resolver_version, :fees_status, :fees_error,
    :fees_confidence, :scan_complete, :txs_parsed, :lower_bound, CAST(:raw_reference AS jsonb)
)
"""


class FeeStatus:
    VERIFIED = "VERIFIED"
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"
    STALE = "STALE"


@dataclass(frozen=True)
class FeeObservation:
    mint: str
    protocol: str | None
    global_fees_sol: float | None
    fees_source: str
    fees_verified: bool
    fees_confidence: float
    fees_observed_at: str
    fees_error: str | None
    fees_status: str
    resolver_version: str = RESOLVER_VERSION
    raw_reference: dict[str, Any] = field(default_factory=dict)
    scan_complete: bool = False
    txs_parsed: int = 0
    lower_bound: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def as_admission_fields(self) -> dict[str, Any]:
        """Fields the canonical gate consumes. Unverified → null fees."""
        verified = bool(self.fees_verified and self.fees_status == FeeStatus.VERIFIED)
        return {
            "global_fees_sol": self.global_fees_sol if verified else None,
            "global_fees_verified": verified,
            "global_fees_source": self.fees_source,
            "global_fees_timestamp": self.fees_observed_at,
            "global_fees_confidence": self.fees_confidence,
            "global_fees_raw": {
                "resolver_version": self.resolver_version,
                "fees_status": self.fees_status,
                "fees_error": self.fees_error,
                "scan_complete": self.scan_complete,
                "txs_parsed": self.txs_parsed,
                "lower_bound": self.lower_bound,
                "raw_reference": self.raw_reference,
            },
        }

    def persist_params(self) -> dict[str, Any]:
        return {
            "mint": self.mint,
            "protocol": self.protocol,
            "global_fees_sol": self.global_fees_sol if self.fees_verified else None,
            "source": self.fees_source,
            "verified": bool(self.fees_verified and self.fees_status == FeeStatus.VERIFIED),
            "observed_at": self.fees_observed_at,
            "resolver_version": self.resolver_version,
            "fees_status": self.fees_status,
            "fees_error": self.fees_error,
            "fees_confidence": self.fees_confidence,
            "scan_complete": self.scan_complete,
            "txs_parsed": self.txs_parsed,
            "lower_bound": self.lower_bound,
            "raw_reference": json.dumps(self.raw_reference or {}),
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_protocol(raw: str | None) -> str:
    return (raw or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def coerce_fees_verified(raw: Any) -> bool | None:
    """Never infer verified=True from a bare number being present."""
    if raw is True:
        return True
    if raw is False:
        return False
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s == "true":
            return True
        if s == "false":
            return False
    return None


def parse_explicit_fee_number(val: Any) -> float | None:
    """Parse an explicit fee field. Negative / NaN / Inf / malformed → None."""
    if val is None or val is True or val is False:
        return None
    if isinstance(val, str) and not val.strip():
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f) or f < 0:
        return None
    if f > 1_000_000:
        f = f / 1e9
    if not math.isfinite(f) or f < 0:
        return None
    return f


def extract_explicit_api_fees(payload: Mapping[str, Any] | None) -> tuple[float | None, str | None, Any]:
    """Return (value, source_key, raw) from a JSON object. No guessing."""
    if not isinstance(payload, dict):
        return None, None, None
    bags: list[Mapping[str, Any]] = [payload]
    for nest in ("coin", "data", "result"):
        sub = payload.get(nest)
        if isinstance(sub, dict):
            bags.append(sub)
    for bag in bags:
        for key in EXPLICIT_FEE_KEYS:
            if key not in bag or bag[key] is None:
                continue
            parsed = parse_explicit_fee_number(bag[key])
            if parsed is None:
                continue
            return parsed, key, bag[key]
    return None, None, None


def _account_keys(tx: Mapping[str, Any]) -> list[str]:
    inner = tx.get("transaction") if isinstance(tx.get("transaction"), dict) else tx
    message = (inner.get("message") if isinstance(inner, dict) else None) or {}
    out: list[str] = []
    for k in message.get("accountKeys") or []:
        if isinstance(k, str):
            out.append(k)
        elif isinstance(k, dict) and k.get("pubkey"):
            out.append(str(k["pubkey"]))
    return out


def parse_tx_protocol_fees(tx: Mapping[str, Any] | None) -> float:
    """SOL credited to published protocol fee recipients in one transaction.

    Per recipient take max(native lamports, WSOL token delta) to avoid
    double-counting wrap/unwrap of the same fee.
    """
    if not isinstance(tx, dict):
        return 0.0
    meta = tx.get("meta") or {}
    if meta.get("err"):
        return 0.0
    keys = _account_keys(tx)
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    native: dict[str, float] = {}
    for i, addr in enumerate(keys):
        if addr not in PROTOCOL_FEE_RECIPIENTS:
            continue
        if i >= len(pre) or i >= len(post):
            continue
        try:
            dlt = (int(post[i]) - int(pre[i])) / 1e9
        except (TypeError, ValueError):
            continue
        if dlt > 0:
            native[addr] = native.get(addr, 0.0) + dlt

    def _tok(arr: Any) -> dict[tuple[str, str], float]:
        out: dict[tuple[str, str], float] = {}
        for b in arr or []:
            if not isinstance(b, dict):
                continue
            owner = b.get("owner")
            mint = b.get("mint")
            if not owner or not mint:
                continue
            amt = (b.get("uiTokenAmount") or {}).get("uiAmount")
            try:
                out[(str(owner), str(mint))] = float(amt or 0.0)
            except (TypeError, ValueError):
                continue
        return out

    pre_t = _tok(meta.get("preTokenBalances"))
    post_t = _tok(meta.get("postTokenBalances"))
    wsol: dict[str, float] = {}
    owners = {o for o, _m in set(pre_t) | set(post_t)}
    for owner in owners:
        if owner not in PROTOCOL_FEE_RECIPIENTS:
            continue
        dlt = post_t.get((owner, WSOL_MINT), 0.0) - pre_t.get((owner, WSOL_MINT), 0.0)
        if dlt > 1e-12:
            wsol[owner] = wsol.get(owner, 0.0) + dlt

    recips = set(native) | set(wsol)
    total = 0.0
    for addr in recips:
        total += max(native.get(addr, 0.0), wsol.get(addr, 0.0))
    return total


def unknown_observation(
    mint: str,
    *,
    protocol: str | None = None,
    source: str = "none",
    error: str | None = None,
    raw: dict[str, Any] | None = None,
    txs_parsed: int = 0,
    scan_complete: bool = False,
    lower_bound: bool = False,
) -> FeeObservation:
    return FeeObservation(
        mint=mint,
        protocol=protocol,
        global_fees_sol=None,
        fees_source=source,
        fees_verified=False,
        fees_confidence=0.0,
        fees_observed_at=_now_iso(),
        fees_error=error,
        fees_status=FeeStatus.UNKNOWN,
        raw_reference=raw or {},
        scan_complete=scan_complete,
        txs_parsed=txs_parsed,
        lower_bound=lower_bound,
    )


def verified_observation(
    mint: str,
    value: float,
    *,
    protocol: str | None,
    source: str,
    confidence: float,
    raw: dict[str, Any] | None = None,
    txs_parsed: int = 0,
    scan_complete: bool = False,
    lower_bound: bool = False,
) -> FeeObservation:
    return FeeObservation(
        mint=mint,
        protocol=protocol,
        global_fees_sol=float(value),
        fees_source=source,
        fees_verified=True,
        fees_confidence=float(confidence),
        fees_observed_at=_now_iso(),
        fees_error=None,
        fees_status=FeeStatus.VERIFIED,
        raw_reference=raw or {},
        scan_complete=scan_complete,
        txs_parsed=txs_parsed,
        lower_bound=lower_bound,
    )


def is_fresh(obs: FeeObservation, *, max_age_sec: float = DEFAULT_MAX_AGE_SEC) -> bool:
    try:
        ts = datetime.fromisoformat(obs.fees_observed_at.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    age = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
    return age <= float(max_age_sec)


def mark_stale(obs: FeeObservation) -> FeeObservation:
    return FeeObservation(
        mint=obs.mint,
        protocol=obs.protocol,
        global_fees_sol=obs.global_fees_sol,
        fees_source=obs.fees_source,
        fees_verified=False,
        fees_confidence=obs.fees_confidence,
        fees_observed_at=obs.fees_observed_at,
        fees_error="STALE",
        fees_status=FeeStatus.STALE,
        resolver_version=obs.resolver_version,
        raw_reference=obs.raw_reference,
        scan_complete=obs.scan_complete,
        txs_parsed=obs.txs_parsed,
        lower_bound=obs.lower_bound,
    )


@dataclass
class FeeResolverStats:
    resolve_start: int = 0
    resolve_success: int = 0
    resolve_unknown: int = 0
    resolve_error: int = 0
    fee_verified: int = 0
    fee_unknown: int = 0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            total = self.fee_verified + self.fee_unknown
            rate = (self.fee_verified / total) if total else None
            return {
                "fee_resolve_start": self.resolve_start,
                "fee_resolve_success": self.resolve_success,
                "fee_resolve_unknown": self.resolve_unknown,
                "fee_resolve_error": self.resolve_error,
                "fee_verified": self.fee_verified,
                "fee_unknown": self.fee_unknown,
                "fee_verified_rate": rate,
                "resolver_version": RESOLVER_VERSION,
            }

    def reset(self) -> None:
        with self._lock:
            self.resolve_start = 0
            self.resolve_success = 0
            self.resolve_unknown = 0
            self.resolve_error = 0
            self.fee_verified = 0
            self.fee_unknown = 0


fee_resolver_stats = FeeResolverStats()

_cache: dict[str, tuple[float, FeeObservation]] = {}
_cache_lock = Lock()


def cache_get(mint: str, *, ttl: float = DEFAULT_CACHE_TTL_SEC) -> FeeObservation | None:
    with _cache_lock:
        hit = _cache.get(mint)
        if not hit:
            return None
        exp, obs = hit
        if time.monotonic() > exp:
            _cache.pop(mint, None)
            return None
        return obs


def cache_put(obs: FeeObservation, *, ttl: float = DEFAULT_CACHE_TTL_SEC) -> None:
    with _cache_lock:
        _cache[obs.mint] = (time.monotonic() + float(ttl), obs)


def cache_clear() -> None:
    with _cache_lock:
        _cache.clear()


def _http_json(url: str, *, data: bytes | None = None, timeout: float = 20.0) -> Any:
    headers = _HTTP_RPC_HEADERS if data is not None else _HTTP_GET_HEADERS
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _rpc(rpc_urls: Iterable[str], method: str, params: list[Any]) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    last_err: str | None = None
    for url in rpc_urls:
        if "helius" in str(url).lower():
            continue
        try:
            body = _http_json(url, data=payload, timeout=25.0)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
            last_err = str(exc)[:160]
            continue
        if not isinstance(body, dict):
            continue
        if body.get("error"):
            last_err = str(body.get("error"))[:160]
            continue
        return body.get("result")
    raise RuntimeError(last_err or "rpc_failed")


class FeeResolver:
    """Synchronous resolver. Safe to call from tests and CLI. No secrets logged."""

    def __init__(
        self,
        *,
        rpc_urls: Iterable[str] | None = None,
        max_txs: int = DEFAULT_MAX_TXS,
        trade_pages: int = DEFAULT_TRADE_PAGES,
        pass_threshold_sol: float = DEFAULT_PASS_THRESHOLD_SOL,
        cache_ttl_sec: float = DEFAULT_CACHE_TTL_SEC,
        http_get: Callable[[str], Any] | None = None,
        rpc_call: Callable[[str, list[Any]], Any] | None = None,
    ) -> None:
        cleaned: list[str] = []
        for u in (tuple(rpc_urls) if rpc_urls else DEFAULT_RPC_URLS):
            if u and "helius" not in str(u).lower() and str(u) not in cleaned:
                cleaned.append(str(u))
        self.rpc_urls = tuple(cleaned) or DEFAULT_RPC_URLS
        self.max_txs = int(max_txs)
        self.trade_pages = int(trade_pages)
        self.pass_threshold_sol = float(pass_threshold_sol)
        self.cache_ttl_sec = float(cache_ttl_sec)
        self._http_get = http_get
        self._rpc_call = rpc_call

    def _get(self, url: str) -> Any:
        if self._http_get:
            return self._http_get(url)
        return _http_json(url)

    def _rpc(self, method: str, params: list[Any]) -> Any:
        if self._rpc_call:
            return self._rpc_call(method, params)
        return _rpc(self.rpc_urls, method, params)

    def resolve(
        self,
        mint: str,
        *,
        protocol: str | None = None,
        pool: str | None = None,
        use_cache: bool = True,
    ) -> FeeObservation:
        mint_s = (mint or "").strip()
        proto = _norm_protocol(protocol)
        fee_resolver_stats.resolve_start += 1
        t0 = time.monotonic()
        if not mint_s:
            fee_resolver_stats.resolve_error += 1
            return unknown_observation("", error="INVALID_MINT")
        if use_cache:
            cached = cache_get(mint_s, ttl=self.cache_ttl_sec)
            if cached is not None:
                return cached
        try:
            obs = self._resolve_uncached(mint_s, protocol=proto or protocol, pool=pool)
        except Exception as exc:
            fee_resolver_stats.resolve_error += 1
            fee_resolver_stats.fee_unknown += 1
            obs = unknown_observation(
                mint_s,
                protocol=protocol,
                source="resolver_error",
                error=f"{type(exc).__name__}:{str(exc)[:120]}",
            )
            _log("fee_resolve_error", mint_s, protocol, obs, t0)
            cache_put(obs, ttl=min(15.0, self.cache_ttl_sec))
            return obs

        if obs.fees_verified:
            fee_resolver_stats.resolve_success += 1
            fee_resolver_stats.fee_verified += 1
            _log("fee_resolve_success", mint_s, protocol, obs, t0)
        else:
            fee_resolver_stats.resolve_unknown += 1
            fee_resolver_stats.fee_unknown += 1
            _log("fee_resolve_unknown", mint_s, protocol, obs, t0)
        cache_put(obs, ttl=self.cache_ttl_sec)
        return obs

    def _resolve_uncached(
        self,
        mint: str,
        *,
        protocol: str | None,
        pool: str | None,
    ) -> FeeObservation:
        # 1. Explicit API field (pump.fun coin JSON).
        api_obs = self._from_pump_coin_api(mint, protocol=protocol)
        if api_obs is not None:
            return api_obs

        proto = _norm_protocol(protocol)
        if proto and proto not in PUMP_FAMILY:
            return unknown_observation(
                mint,
                protocol=protocol,
                source="unsupported_protocol",
                error="NO_FEE_MECHANISM",
                raw={"protocol": proto},
            )

        # 2. On-chain protocol fee recipients (pump family, including mayhem).
        return self._from_onchain_recipients(mint, protocol=protocol, pool=pool)

    def _from_pump_coin_api(self, mint: str, *, protocol: str | None) -> FeeObservation | None:
        try:
            payload = self._get(PUMP_COIN_V3.format(mint=mint))
        except Exception:
            return None
        value, key, raw = extract_explicit_api_fees(payload if isinstance(payload, dict) else None)
        if value is None or key is None:
            return None
        return verified_observation(
            mint,
            value,
            protocol=protocol,
            source=f"pump.fun/{key}",
            confidence=1.0,
            raw={"field": key, "raw": raw},
            scan_complete=True,
            lower_bound=False,
        )

    def _from_onchain_recipients(
        self,
        mint: str,
        *,
        protocol: str | None,
        pool: str | None,
    ) -> FeeObservation:
        trades, has_more = self._fetch_trades(mint)
        if not trades:
            return unknown_observation(
                mint,
                protocol=protocol,
                source="onchain.pump.fee_recipient",
                error="NO_TRADES",
                raw={"pool": pool},
            )
        trades = sorted(
            trades,
            key=lambda r: float(r.get("amountSol") or 0) if _is_num(r.get("amountSol")) else 0.0,
            reverse=True,
        )
        total = 0.0
        parsed = 0
        refs: list[str] = []
        errors = 0
        for row in trades[: self.max_txs]:
            sig = row.get("tx") or row.get("signature")
            if not sig:
                continue
            try:
                tx = self._rpc(
                    "getTransaction",
                    [
                        str(sig),
                        {
                            "encoding": "jsonParsed",
                            "maxSupportedTransactionVersion": 0,
                            "commitment": "confirmed",
                        },
                    ],
                )
            except Exception:
                errors += 1
                continue
            if not isinstance(tx, dict):
                errors += 1
                continue
            fee = parse_tx_protocol_fees(tx)
            parsed += 1
            if fee > 0:
                total += fee
                if len(refs) < 8:
                    refs.append(str(sig))
            if total + 1e-12 >= self.pass_threshold_sol:
                return verified_observation(
                    mint,
                    total,
                    protocol=protocol,
                    source="onchain.pump.fee_recipient",
                    confidence=1.0,
                    raw={
                        "tx_refs": refs,
                        "observed_protocol_fees_sol": total,
                        "early_exit": True,
                        "pool": pool,
                    },
                    txs_parsed=parsed,
                    scan_complete=False,
                    lower_bound=True,
                )

        scan_complete = (not has_more) and errors == 0 and parsed >= len(trades)
        # Lower bound < 1 SOL cannot prove the gate either way unless we captured
        # protocol+creator all-time. Protocol-only shortfall → UNKNOWN.
        return unknown_observation(
            mint,
            protocol=protocol,
            source="onchain.pump.fee_recipient",
            error="INCOMPLETE_OR_BELOW_THRESHOLD",
            raw={
                "observed_protocol_fees_sol": total,
                "tx_refs": refs,
                "has_more": has_more,
                "errors": errors,
                "pool": pool,
            },
            txs_parsed=parsed,
            scan_complete=scan_complete,
            lower_bound=total > 0,
        )

    def _fetch_trades(self, mint: str) -> tuple[list[dict[str, Any]], bool]:
        out: list[dict[str, Any]] = []
        cursor: str | None = None
        has_more = False
        for _page in range(self.trade_pages):
            url = PUMP_V2_TRADES.format(mint=mint) + "?limit=100"
            if cursor:
                url += f"&cursor={cursor}"
            try:
                data = self._get(url)
            except Exception:
                break
            if not isinstance(data, dict):
                break
            rows = data.get("trades")
            if not isinstance(rows, list) or not rows:
                break
            for r in rows:
                if isinstance(r, dict):
                    out.append(r)
            pag = data.get("pagination") if isinstance(data.get("pagination"), dict) else {}
            has_more = bool(pag.get("hasMore"))
            cursor = str(pag.get("nextCursor")) if pag.get("nextCursor") else None
            if not has_more or not cursor:
                has_more = False
                break
        return out, has_more


def _is_num(v: Any) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _log(event: str, mint: str, protocol: str | None, obs: FeeObservation, t0: float) -> None:
    try:
        import structlog

        structlog.get_logger(__name__).info(
            event,
            mint=mint[:16],
            protocol=protocol,
            source=obs.fees_source,
            latency_ms=int((time.monotonic() - t0) * 1000),
            status=obs.fees_status,
            resolver_version=RESOLVER_VERSION,
            verified=obs.fees_verified,
            txs_parsed=obs.txs_parsed,
        )
    except Exception:
        pass
