# Free buyer capture — source verification

Order:

1. PRIMARY  pump.fun swap-api v2  `GET https://swap-api.pump.fun/v2/coins/{mint}/trades?limit=&cursor=`
2. FALLBACK public Solana RPC `getSignaturesForAddress` + `getTransaction` jsonParsed
3. OPTIONAL Helius enhanced txs (`STINKY_ENABLE_HELIUS=true`)

The collector is provider-agnostic. `ChainClient.fetch_trades_for_mint` records:

- `trade_source`
- `trade_source_status`
- `trade_source_latency_ms`
- `trade_source_error`
- `trade_source_coverage`

via `last_trade_source_status()`.

## Pump v2 live probe (2026-08-30)

Mint: `AfGdjAp9djSaqJxzYo3t6jy8tJA3o2aDPHoZ57Egpump`

| Check | Result |
| --- | --- |
| HTTP | 200 |
| Page size | `limit=20` returned 20; `limit=100` supported |
| Fields | `tx`, `type` buy/sell, `userAddress`, `amountSol`, `timestamp`, `program=pump_amm`, `baseAmount` |
| Pagination | `{nextCursor, hasMore, limit}` — page 2 returned 20 new rows, 0 signature overlap |
| Direction | 11 buy / 9 sell on first page |
| Unique wallets | 11 |
| Duplicates | collector `dedupe_trades` by (signature, wallet, side) |
| Unknown type | `classify_side("swap")` → None; not guessed as buy or sell |
| Program/pool wallets | rejected (`pAMMBay…`, system program, token program) |

### Historical / mutation

Trades can paginate into the past via cursor. We have not proven that rows are immutable; treat as append-mostly. If a signature reappears it is deduped.

### Rate limits

Observable: HTTP 429 on burst. Collector paces 0.25s between pump pages.

### Coverage

Pump v2 covers post-migration pump AMM trades for the mint. It does not cover every historical pre-migration bonding-curve trade. Incomplete for full token lifetime — marked incomplete. RPC fallback parses token-balance deltas only (does not infer sell from SOL movement alone).

### Attribution rules

- Verify mint, signature, wallet, direction, amount
- Unknown direction → drop (TradeClass stays unknown; never guess)
- Pool / program addresses excluded
- Zero amounts rejected by ranking (`min_sol`)
