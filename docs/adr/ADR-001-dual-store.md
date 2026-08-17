# ADR-001: Dual Store (PostgreSQL + TimescaleDB + Neo4j)

**Status:** Accepted  
**Date:** 2026-08-07  
**Deciders:** Lead Architect / CTO  

## Context
Stinky OS requires both strong transactional/time-series semantics and efficient multi-hop relationship queries at scale for entity resolution and pattern discovery.

## Decision
- PostgreSQL 16 + TimescaleDB is the system of record for events, scores, features, models, audit logs, and user data.
- Neo4j 5.x is the system of record for the live entity-relationship graph.
- An event-driven bidirectional synchronization layer keeps the stores consistent.

## Alternatives Considered
- Pure PostgreSQL with recursive CTEs or Apache AGE
- Pure Neo4j
- Single store + heavy materialized views

## Consequences
- Higher operational complexity (two systems to operate)
- Excellent query performance for both analytical and graph workloads
- Clear ownership boundaries reduce accidental coupling
- Enables Time Machine and multi-hop discovery without compromise
