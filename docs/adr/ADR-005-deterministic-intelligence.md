# ADR-005: Deterministic Intelligence

**Status:** Accepted  
**Date:** 2026-08-07  

## Context
Users must be able to trust and audit every score and prediction. AI hallucination of scores is unacceptable.

## Decision
AI never determines truth.
Pipeline: Blockchain → Events → Feature Engineering → Entity Resolution → Deterministic Score Engine → Prediction Engine → AI Explanation → User

AI explains, researches, summarizes. AI never invents scores.

## Consequences
- Full explainability and auditability
- AI layer remains valuable for narrative and research
- Score engine must remain purely deterministic / statistical
