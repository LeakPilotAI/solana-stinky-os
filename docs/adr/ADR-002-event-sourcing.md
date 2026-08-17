# ADR-002: Event Sourcing

**Status:** Accepted  
**Date:** 2026-08-07  

## Context
We need full reproducibility for Time Machine, Simulator, model validation, backtesting, and disaster recovery.

## Decision
The platform is event-sourced. Every blockchain observation becomes an immutable event. No intelligence service owns canonical state. All derived state is reproducible by replaying the event log.

Pipeline:
Blockchain → Immutable Event Log → Feature Engineering → Entity Resolution → Score Engine → Materialized Views → API → Frontend

## Consequences
- Strong auditability and reproducibility
- Enables Simulation and Time Machine natively
- Slightly higher storage and complexity for projections
- Requires careful event schema versioning
