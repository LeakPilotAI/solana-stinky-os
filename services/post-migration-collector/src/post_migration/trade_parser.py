"""Parse swap / transfer activity into ObservedTrade records.

Supports:
- Helius enhanced transaction shape
- Deterministic fixture / normalized internal shape

Sell Attribution v1:
  - Token outflow from a user wallet = SELL
  - Token inflow to a user wallet = BUY
  - Prefer feePayer when present; never treat program/pool accounts as traders
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from post_migration.models import ObservedTrade, TradeClass, TradeSide


def _ts(v: Any) -> datetime:
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)
    if isinstance(v, (int, float)):
        if v > 1e12:
            v = v / 1000.0
        return datetime.fromtimestamp(v, tz=timezone.utc)
    if isinstance(v, str):
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    return datetime.now(timezone.utc)


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _sol_from_amount(amt: float | None) -> float | None:
    """Normalize Helius native amounts (lamports or SOL) to SOL.

    nativeTransfers are almost always lamports. Values >= 10_000
    (~0.00001 SOL) are treated as lamports; smaller values left as SOL.
    """
    if amt is None:
        return None
    if abs(amt) >= 10_000:
        return amt / 1e9
    return amt


def classify_side(raw: Any) -> TradeSide | None:
    """Map a provider side string to BUY/SELL. Unknown → None (never guess)."""
    s = str(raw or "").strip().lower()
    if s in ("buy", "buy_exact_in", "buy_exact_out"):
        return TradeSide.BUY
    if s in ("sell", "sell_exact_in", "sell_exact_out"):
        return TradeSide.SELL
    return None


def trade_identity(t: ObservedTrade) -> tuple[str, str, str]:
    return (t.signature, t.wallet, t.side.value)


def dedupe_trades(trades: list[ObservedTrade]) -> list[ObservedTrade]:
    """Deduplicate by signature + wallet + side. Keep chronological order."""
    seen: set[tuple[str, str, str]] = set()
    unique: list[ObservedTrade] = []
    for t in trades:
        key = trade_identity(t)
        if key in seen:
            continue
        seen.add(key)
        unique.append(t)
    unique.sort(key=lambda x: (x.traded_at, x.signature))
    return unique


def parse_normalized_trade(raw: dict[str, Any], *, mint: str) -> ObservedTrade | None:
    """Parse a already-normalized trade dict (fixtures / internal)."""
    wallet = raw.get("wallet") or raw.get("address")
    side = classify_side(raw.get("side") or raw.get("type"))
    sig = raw.get("signature") or raw.get("tx")
    if not wallet or side is None or not sig:
        return None
    if raw.get("mint") and raw["mint"] != mint:
        return None
    return ObservedTrade(
        mint=mint,
        wallet=str(wallet),
        side=side,
        signature=str(sig),
        traded_at=_ts(raw.get("traded_at") or raw.get("timestamp") or raw.get("blockTime")),
        slot=_int(raw.get("slot")),
        token_amount=_f(raw.get("token_amount") or raw.get("tokenAmount")),
        sol_amount=_f(raw.get("sol_amount") or raw.get("solAmount")),
        usd_amount=_f(raw.get("usd_amount") or raw.get("usdAmount")),
        price_usd=_f(raw.get("price_usd") or raw.get("priceUsd")),
        meta={"source": raw.get("source", "normalized")},
    )


# Program / system accounts that are never the trader.
_PROGRAM_ACCOUNTS: frozenset[str] = frozenset(
    {
        "11111111111111111111111111111111",
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
        "ComputeBudget111111111111111111111111111111",
        "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
        "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
        "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg",
        "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
        "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
        "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",
        "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
        "JUP4Fb2cqiRUcaTHdrLCGBKqKghvh9j8sH4k6b3p5s1",
        "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
        "SysvarRent111111111111111111111111111111111",
        "SysvarC1ock11111111111111111111111111111111",
    }
)


def _is_user_wallet(addr: str | None) -> bool:
    if not addr or len(addr) < 32:
        return False
    return addr not in _PROGRAM_ACCOUNTS


def parse_helius_swap(tx: dict[str, Any], *, mint: str) -> list[ObservedTrade]:
    """Extract buy/sell legs for `mint` from a Helius enhanced transaction.

    Classification rules (Sell Attribution v1):
      1. Prefer feePayer: if feePayer receives mint → BUY; if feePayer sends mint → SELL
      2. Otherwise: receiver of mint is BUY, sender of mint is SELL (user wallets only)
      3. Merge tokenTransfers + events.swap (no early return that drops sells)
    """
    out: list[ObservedTrade] = []
    signature = tx.get("signature") or tx.get("txHash") or ""
    if not signature:
        return out
    traded_at = _ts(tx.get("timestamp") or tx.get("blockTime"))
    slot = _int(tx.get("slot"))
    fee_payer = tx.get("feePayer")

    def _add(
        wallet: str,
        side: TradeSide,
        token_amount: float | None,
        sol_amount: float | None,
        source: str,
    ) -> None:
        if not _is_user_wallet(wallet):
            return
        tclass = TradeClass.BUY if side == TradeSide.BUY else TradeClass.SELL
        out.append(
            ObservedTrade(
                mint=mint,
                wallet=wallet,
                side=side,
                signature=signature,
                traded_at=traded_at,
                slot=slot,
                token_amount=token_amount,
                sol_amount=sol_amount,
                usd_amount=None,
                price_usd=None,
                trade_class=tclass,
                meta={
                    "source": source,
                    "fee_payer": fee_payer,
                    "trade_class": tclass.value,
                },
            )
        )

    # --- Path A: tokenTransfers ---
    for tr in tx.get("tokenTransfers") or []:
        if tr.get("mint") != mint:
            continue
        from_w = tr.get("fromUserAccount")
        to_w = tr.get("toUserAccount")
        amount = _f(tr.get("tokenAmount"))

        # Prefer feePayer-centric classification (most reliable for user swaps)
        if fee_payer and to_w == fee_payer:
            sol = _sol_for_wallet(tx, fee_payer, TradeSide.BUY)
            _add(fee_payer, TradeSide.BUY, amount, sol, "helius.tt.fee_payer_buy")
            continue
        if fee_payer and from_w == fee_payer:
            sol = _sol_for_wallet(tx, fee_payer, TradeSide.SELL)
            _add(fee_payer, TradeSide.SELL, amount, sol, "helius.tt.fee_payer_sell")
            continue

        # Generic: inflow = buy for receiver, outflow = sell for sender
        if to_w and _is_user_wallet(to_w):
            sol = _sol_for_wallet(tx, to_w, TradeSide.BUY)
            _add(to_w, TradeSide.BUY, amount, sol, "helius.tt.buy")
        if from_w and _is_user_wallet(from_w):
            sol = _sol_for_wallet(tx, from_w, TradeSide.SELL)
            _add(from_w, TradeSide.SELL, amount, sol, "helius.tt.sell")

    # --- Path B: events.swap (always merge; do not skip if tokenTransfers existed) ---
    events = tx.get("events") or {}
    swap = events.get("swap") if isinstance(events, dict) else None
    if isinstance(swap, dict):
        native_in = swap.get("nativeInput") or {}
        native_out = swap.get("nativeOutput") or {}
        token_ins = swap.get("tokenInputs") or []
        token_outs = swap.get("tokenOutputs") or []

        for tin in token_ins:
            if tin.get("mint") != mint:
                continue
            wallet = tin.get("userAccount") or fee_payer
            if not wallet:
                continue
            raw_tok = tin.get("rawTokenAmount")
            tok_amt = (
                _f(raw_tok.get("tokenAmount"))
                if isinstance(raw_tok, dict)
                else _f(tin.get("tokenAmount"))
            )
            # User spent the mint → SELL; they receive SOL (nativeOutput)
            sol = _sol_from_amount(_f(native_out.get("amount")))
            if fee_payer and wallet != fee_payer and _is_user_wallet(fee_payer):
                # Prefer fee payer as the trader when swap is aggregated
                _add(fee_payer, TradeSide.SELL, tok_amt, sol, "helius.swap.sell")
            else:
                _add(str(wallet), TradeSide.SELL, tok_amt, sol, "helius.swap.sell")

        for tout in token_outs:
            if tout.get("mint") != mint:
                continue
            wallet = tout.get("userAccount") or fee_payer
            if not wallet:
                continue
            raw_tok = tout.get("rawTokenAmount")
            tok_amt = (
                _f(raw_tok.get("tokenAmount"))
                if isinstance(raw_tok, dict)
                else _f(tout.get("tokenAmount"))
            )
            # User received the mint → BUY; they spent SOL (nativeInput)
            sol = _sol_from_amount(_f(native_in.get("amount")))
            if fee_payer and wallet != fee_payer and _is_user_wallet(fee_payer):
                _add(fee_payer, TradeSide.BUY, tok_amt, sol, "helius.swap.buy")
            else:
                _add(str(wallet), TradeSide.BUY, tok_amt, sol, "helius.swap.buy")

    # Dedupe within this tx: (wallet, side) keep first
    seen: set[tuple[str, str]] = set()
    deduped: list[ObservedTrade] = []
    for t in out:
        key = (t.wallet, t.side.value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(t)
    return deduped


def _sol_for_wallet(tx: dict[str, Any], wallet: str, side: TradeSide) -> float | None:
    total = 0.0
    found = False
    for nt in tx.get("nativeTransfers") or []:
        amt = _f(nt.get("amount"))
        if amt is None:
            continue
        sol = _sol_from_amount(amt)
        if sol is None:
            continue
        if side == TradeSide.BUY and nt.get("fromUserAccount") == wallet:
            total += sol
            found = True
        if side == TradeSide.SELL and nt.get("toUserAccount") == wallet:
            total += sol
            found = True
    return total if found else None



# Additional non-trader accounts (programs, vaults, known system)
_EXTRA_BLOCK: frozenset[str] = frozenset(
    {
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
        "11111111111111111111111111111111",
        "ComputeBudget111111111111111111111111111111",
        "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
        "SysvarRent111111111111111111111111111111111",
        "SysvarC1ock11111111111111111111111111111111",
        # Pump.fun / pumpswap related program ids
        "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
        "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
        "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg",
    }
)

def _looks_like_pool_or_vault(addr: str) -> bool:
    """Heuristic: very short or known program patterns — conservative."""
    if not addr or len(addr) < 32:
        return True
    return False

DEFAULT_BUYER_DENYLIST: frozenset[str] = _PROGRAM_ACCOUNTS | _EXTRA_BLOCK


def rank_early_buyers(
    buys: list[ObservedTrade],
    *,
    max_buyers: int,
    min_sol: float,
    exclude: set[str] | frozenset[str] | None = None,
) -> list[ObservedTrade]:
    """Select first N meaningful distinct-wallet buys (chronological).

    Skips wallets in `exclude` (pool address, AMM programs, config denylist).
    """
    blocked = set(DEFAULT_BUYER_DENYLIST)
    if exclude:
        blocked |= set(exclude)
    if exclude:
        blocked.update(a for a in exclude if a)

    ordered = sorted(buys, key=lambda t: (t.traded_at, t.signature))
    seen: set[str] = set()
    ranked: list[ObservedTrade] = []
    for t in ordered:
        if t.side != TradeSide.BUY:
            continue
        if t.wallet in seen:
            continue
        if t.wallet in blocked:
            continue
        if not t.is_meaningful(min_sol):
            continue
        seen.add(t.wallet)
        ranked.append(
            t.model_copy(
                update={"is_early_buyer": True, "early_rank": len(ranked) + 1}
            )
        )
        if len(ranked) >= max_buyers:
            break
    return ranked


def parse_pump_v2_trade(raw: dict[str, Any], *, mint: str) -> ObservedTrade | None:
    """Parse one row from swap-api.pump.fun /v2/coins/:mint/trades (free, no key)."""
    wallet = raw.get("userAddress") or raw.get("user") or raw.get("wallet")
    side = classify_side(raw.get("type") or raw.get("side"))
    sig = raw.get("tx") or raw.get("signature") or raw.get("txHash")
    if not wallet or side is None or not sig:
        return None
    if raw.get("mint") and str(raw["mint"]) != mint:
        return None
    if not _is_user_wallet(str(wallet)):
        return None
    tclass = TradeClass.BUY if side == TradeSide.BUY else TradeClass.SELL
    slot = None
    slot_raw = raw.get("slotIndexId") or raw.get("slot")
    if isinstance(slot_raw, int):
        slot = slot_raw
    elif isinstance(slot_raw, str) and slot_raw.isdigit():
        # slotIndexId looks like 0004427886080001150000 -> slot is first 12 digits
        try:
            slot = int(slot_raw[:12])
        except ValueError:
            slot = None
    return ObservedTrade(
        mint=mint,
        wallet=str(wallet),
        side=side,
        signature=str(sig),
        traded_at=_ts(raw.get("timestamp") or raw.get("blockTime")),
        slot=slot,
        token_amount=_f(raw.get("baseAmount") or raw.get("token_amount")),
        sol_amount=_f(raw.get("amountSol") or raw.get("quoteAmount") or raw.get("sol_amount")),
        usd_amount=_f(raw.get("amountUsd") or raw.get("usd_amount")),
        price_usd=_f(raw.get("priceUsd") or raw.get("fillPriceUsd")),
        trade_class=tclass,
        meta={
            "source": "pump.v2",
            "program": raw.get("program"),
            "trade_class": tclass.value,
        },
    )


def parse_rpc_json_parsed(tx: dict[str, Any], *, mint: str) -> list[ObservedTrade]:
    """Extract buy/sell from a public-RPC getTransaction (jsonParsed) result."""
    out: list[ObservedTrade] = []
    if not isinstance(tx, dict):
        return out
    meta = tx.get("meta") or {}
    if meta.get("err"):
        return out
    inner = tx.get("transaction") if isinstance(tx.get("transaction"), dict) else tx
    message = (inner.get("message") if isinstance(inner, dict) else None) or {}
    account_keys = message.get("accountKeys") or []
    keys: list[str] = []
    for k in account_keys:
        if isinstance(k, str):
            keys.append(k)
        elif isinstance(k, dict):
            pk = k.get("pubkey") or k.get("pubkey")
            if pk:
                keys.append(str(pk))
    fee_payer = keys[0] if keys else None
    signature = ""
    sigs = inner.get("signatures") if isinstance(inner, dict) else None
    if isinstance(sigs, list) and sigs:
        signature = str(sigs[0])
    if not signature:
        signature = str(tx.get("signature") or tx.get("transaction", {}).get("signatures", [""])[0] or "")
    if not signature:
        return out
    traded_at = _ts(tx.get("blockTime") or tx.get("timestamp"))
    slot = _int(tx.get("slot"))

    def _ui(b: dict[str, Any]) -> float:
        amt = (b.get("uiTokenAmount") or {}) if isinstance(b, dict) else {}
        return float(amt.get("uiAmount") or 0.0)

    pre: dict[str, float] = {}
    post: dict[str, float] = {}
    for b in meta.get("preTokenBalances") or []:
        if not isinstance(b, dict) or b.get("mint") != mint:
            continue
        owner = b.get("owner")
        if owner:
            pre[str(owner)] = _ui(b)
    for b in meta.get("postTokenBalances") or []:
        if not isinstance(b, dict) or b.get("mint") != mint:
            continue
        owner = b.get("owner")
        if owner:
            post[str(owner)] = _ui(b)
    owners = set(pre) | set(post)
    pre_sol = meta.get("preBalances") or []
    post_sol = meta.get("postBalances") or []
    key_index = {addr: i for i, addr in enumerate(keys)}

    for owner in owners:
        if not _is_user_wallet(owner):
            continue
        delta = post.get(owner, 0.0) - pre.get(owner, 0.0)
        if abs(delta) < 1e-12:
            continue
        # Token-balance delta is the only accepted direction signal.
        # Do not infer a SELL merely because SOL moved.
        side = TradeSide.BUY if delta > 0 else TradeSide.SELL
        tclass = TradeClass.BUY if side == TradeSide.BUY else TradeClass.SELL
        sol_amount = None
        idx = key_index.get(owner)
        if idx is not None and idx < len(pre_sol) and idx < len(post_sol):
            try:
                sol_delta = (int(post_sol[idx]) - int(pre_sol[idx])) / 1e9
                sol_amount = abs(sol_delta)
            except (TypeError, ValueError):
                sol_amount = None
        if not _is_user_wallet(owner):
            continue
        wallet = owner
        out.append(
            ObservedTrade(
                mint=mint,
                wallet=wallet,
                side=side,
                signature=signature,
                traded_at=traded_at,
                slot=slot,
                token_amount=abs(delta),
                sol_amount=sol_amount,
                usd_amount=None,
                price_usd=None,
                trade_class=tclass,
                meta={"source": "rpc.jsonParsed", "owner": owner, "fee_payer": fee_payer},
            )
        )
    seen: set[tuple[str, str]] = set()
    deduped: list[ObservedTrade] = []
    for t in out:
        key = (t.wallet, t.side.value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(t)
    return deduped
