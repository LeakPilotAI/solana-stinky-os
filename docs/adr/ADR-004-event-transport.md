# ADR-004: Event Transport Abstraction

**Status:** Accepted  
**Date:** 2026-08-07  

## Context
Redis Streams is the initial transport, but the system must remain free to switch to Kafka, NATS, or RabbitMQ without rewriting business logic.

## Decision
All producers and consumers communicate exclusively through an Event Transport Interface. No business logic may depend directly on Redis (or any concrete broker).

## Consequences
- Future transport swaps are low-cost
- Slight abstraction overhead
- Forces clean producer/consumer contracts
