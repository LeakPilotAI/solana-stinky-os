# ADR-008: C4 Architecture Documentation

**Status:** Accepted  
**Date:** 2026-08-07  

## Context
Long-lived platforms need clear, permanent architectural documentation that survives team changes.

## Decision
Before coding any service we produce and maintain:
1. System Context Diagram
2. Container Diagram
3. Component Diagrams for every service
4. Deployment Diagram
5. Sequence diagrams for critical flows (Launch → Event → Entity Resolution → Score → Alert)

These diagrams are permanent project documentation.

## Consequences
- Higher upfront documentation cost
- Dramatically better onboarding and decision traceability
