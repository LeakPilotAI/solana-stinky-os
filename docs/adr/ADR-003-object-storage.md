# ADR-003: Object Storage

**Status:** Accepted  
**Date:** 2026-08-07  

## Context
ML artifacts, historical snapshots, replay datasets, large payloads, and training data must be stored durably and cheaply.

## Decision
- Development: MinIO
- Production: S3-compatible object storage
- Object storage is used for binary/large objects only; it is never a database of record.

## Consequences
- Clean separation of concerns
- Cost-efficient storage for large artifacts
- Requires careful key naming and lifecycle policies
