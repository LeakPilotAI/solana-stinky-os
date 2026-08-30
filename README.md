# Stinky OS

**The definitive intelligence operating system for the Solana blockchain.**

Entity-first. Event-sourced. Explainable. Continuously learning.

---

## Quick start (VS Code)

### 1. Open the project

```bash
# From the folder that contains stinky-os
code stinky-os
```

Or **File → Open Folder…** and select `stinky-os`.

### 2. Create a virtual environment

```bash
cd stinky-os
python3.12 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

VS Code should detect the interpreter automatically (`.venv/bin/python`).

### 3. Install packages

```bash
pip install -e "./packages/stinky-core[dev]"
pip install -e "./services/event-log[dev]"
```

### 4. Start infrastructure

```bash
docker compose up -d
```

This starts (host ports offset from 5432 / 6379 / 8000 so other local stacks can keep those):

| Service                  | Host port(s)   | Purpose                    |
|--------------------------|----------------|----------------------------|
| PostgreSQL + TimescaleDB | **5433**       | Event store + analytics    |
| Redis                    | **6380**       | Event transport (Streams)  |
| MinIO                    | **9010 / 9011**| Object storage (S3-compat) |

Schema is applied automatically on first Postgres start via `001_initial_schema.sql`.

### 5. Environment

```bash
cp .env.example .env
# defaults already point at 5433 / 6380 / 9010
```

### 6. Run the Event Log service

```bash
cd services/event-log
uvicorn event_log.api:app --reload --port 8001
```

Health check: http://localhost:8001/health  
OpenAPI docs: http://localhost:8001/docs

### 7. Run tests

```bash
# From repo root (with venv active)
pytest packages/stinky-core -q
pytest services/event-log -q
```

---

## Repository layout

```
stinky-os/
├── packages/
│   └── stinky-core/          # Shared events, transport, quality, models
├── services/
│   └── event-log/            # Immutable event store + Data Quality gate
├── docs/
│   └── adr/                  # Architecture Decision Records
├── infra/                    # (future) k8s, terraform
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Architecture (locked)

- **Event-sourced** – all derived state is replayable
- **Dual store** – PostgreSQL/Timescale + Neo4j (graph added in later module)
- **Transport abstraction** – Redis Streams today, Kafka/NATS swappable
- **Deterministic scores** – AI explains, never invents scores
- **Versioned features & models** – full reproducibility
- **Data Quality layer** – invalid events never reach intelligence services

See `docs/adr/` for the full set of ADRs.

---

## Current status

| Module              | Status              |
|---------------------|---------------------|
| stinky-core         | ✅ v0.1.0           |
| event-log           | ✅ v0.1.0           |
| Feature Engineering | 🚧 next             |
| Entity Resolution   | pending             |
| Stinky Score Engine | pending             |
| Graph (Neo4j)       | pending             |
| AI Research layer   | pending             |
| Frontend            | pending             |

---

## Development rules (Execution Mode)

- One production-quality module at a time
- No placeholders / TODOs / pseudocode
- Every module ships with tests, docs, config, logging, health checks
- Architecture is locked except for critical flaws
- New features require explicit approval

---

**Stinky Labs** – Build the platform. Profile every meaningful entity on Solana.
