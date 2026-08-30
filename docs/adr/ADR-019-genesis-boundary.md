# ADR-019 Genesis project boundary

Status: Accepted
Date: 2026-08-30

## Decision

Genesis (Stinky OS / Project-Genesis / solana-stinky-os) is a **Solana speculative-asset intelligence OS**.

It is not a general investment platform, brokerage, stock/ETF analyzer, perpetual/futures engine, or day-trading system.

A feature belongs in Genesis only if it directly serves:

raw Solana/market data → validation → post-migration detection → Gate 1 → immutable investigation → observation timeline → entity/wallet memory → outcome → pattern discovery → quality state → explainable intelligence → browser / Discord.

If a future idea could belong to either a general trading product or Genesis, the default is **do not add it**.

## Infrastructure that is allowed

Generic local infrastructure is not product logic:

- Postgres / Redis / object storage
- event transport
- Docker port offsets so other local stacks can keep 5432 / 6379 / 8000
- process-stop scripts that only kill Project-Genesis processes

Those stay. They are not a second product.

## Forbidden in this repository

Trading strategies, investment scoring, brokerage integrations, equities/ETF models, perpetual/futures logic, position sizing, trade execution, portfolio management, and any sibling-product terminology, routes, schemas, Discord channels, or datasets.

## Quality dips

A quality dip is deterioration in the **observed setup** of a Gate-1 Solana token (liquidity, volume structure, sell pressure, entity evidence). It is not "price went down, therefore buy" and not a trade signal.
