# ADR-006: Versioned Features

**Status:** Accepted  
**Date:** 2026-08-07  

## Context
Historical predictions and scores must remain reproducible years later.

## Decision
Every feature, feature set, model, and prediction is explicitly versioned. Feature Definition Version + Feature Set Version + Model Version + Prediction Version are stored with every derived artifact.

## Consequences
- Perfect reproducibility
- Slightly higher storage and bookkeeping
- Enables safe model evolution and A/B testing
