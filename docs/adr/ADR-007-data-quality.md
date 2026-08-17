# ADR-007: Data Quality Layer

**Status:** Accepted  
**Date:** 2026-08-07  

## Context
Downstream intelligence must never consume invalid, duplicate, or incomplete events.

## Decision
A dedicated Data Quality layer sits between ingestion and Feature Engineering. Responsibilities include schema validation, duplicate detection, malformed event handling, missing-data detection, RPC reconciliation, retry queues, provider failover, dead-letter queue, and integrity verification.

## Consequences
- Higher reliability of all intelligence outputs
- Additional latency and operational surface
- Clear isolation of dirty data
