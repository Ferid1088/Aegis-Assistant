# Aegis

**Project Name:** Aegis  
**Version:** 0.1.0  
**License:** MIT  
**Python Version:** >=3.14  
**Node Version:** 20 (Alpine, see `ui/Dockerfile`)  
**Docker:** Docker Compose (see `docker-compose.yml`); images published to `ghcr.io/ferid1088/aegis-assistant-*`  
**Build Status:** See [Releases](.github/workflows/release.yml) workflow (`v*` tags)  

## **Table of Contents**
1. [Project Vision](#project-vision)
2. [About the Project Name](#about-the-project-name)
3. [Features](#features)
4. [Architecture Overview](#architecture-overview)
5. [Technology Stack](#technology-stack)
6. [Installation](#installation)
7. [Docker](#docker)
8. [Hardware Requirements](#hardware-requirements)
9. [Repository Structure](#repository-structure)
10. [Ingestion Pipeline](#ingestion-pipeline)
11. [Query Pipeline](#query-pipeline)
12. [Knowledge Graph](#knowledge-graph)
13. [Authentication Flow](#authentication-flow)
14. [Authorization Flow](#authorization-flow)
15. [Document Accessibility](#document-accessibility)
16. [Security Layers](#security-layers)
17. [Licensing Strategy](#licensing-strategy)
18. [Database Design](#database-design)
19. [API Documentation](#api-documentation)
20. [Configuration](#configuration)
21. [Logging](#logging)
22. [Monitoring](#monitoring)
23. [Testing](#testing)
24. [CI/CD](#ci-cd)
25. [Performance](#performance)
26. [Security Considerations](#security-considerations)
27. [Future Roadmap](#future-roadmap)
28. [Contributing](#contributing)
29. [License](#license)
30. [Authors](#authors)

## Project Vision
Aegis exists to solve the challenges of integrating advanced AI-driven RAG solutions into environments with the strictest data privacy (Datenschutz) regulations. Built from the ground up as a completely locally isolated and air-gapped system, Aegis ensures that sensitive data never leaves the local infrastructure. It streamlines document management workflows and delivers AI-driven insights while guaranteeing absolute sovereignty over intellectual property. The target users include developers, DevOps engineers, AI engineers, and system administrators who require a secure, compliant environment where external data leakage is architecturally impossible.

## About the Project Name
The project is named Aegis—evoking the mythical shield of absolute protection and safeguarding—to reflect its design as a completely local, air-gapped RAG and document management system. By operating entirely within an isolated environment with zero external dependencies or internet connectivity, Aegis ensures that sensitive enterprise data, proprietary knowledge, and intellectual property remain securely locked down and entirely under your physical control.

## Features

### Authentication & Identity
- Local username/password login with JWT access (15 min) + refresh (14 days) tokens (`rag/api/routers/auth.py`, `rag/crosscutting/security/tokens.py`)
- TOTP-based MFA enroll/verify, secrets encrypted at rest (`rag/crosscutting/security/mfa.py`)
- Short-lived MFA-pending token as an intermediate state between password check and TOTP verification (5 min TTL)
- Account lockout after repeated failed logins (threshold 5, 900s duration) (`rag/crosscutting/security/lockout.py`)
- Session listing/revocation per user (`rag/crosscutting/security/session_service.py`)
- Keystore: master key wraps per-purpose data-encryption-keys (e.g. `mfa`, `backup`) (`rag/crosscutting/security/keystore.py`)
- License-gate seam for seat-capped auto-provisioning (SSO/AD) — currently a stub that always allows provisioning (`rag/crosscutting/security/license_gate.py`, see [Licensing Strategy](#licensing-strategy))

### RBAC & Admin
- Departments, ranked per-department Access Levels, Roles, and Role→Permission / Role→AccessLevel grants (`rag/api/routers/admin_rbac.py`)
- RBAC resolved fresh from the database on every request — deliberately uncached so permission changes apply immediately (`rag/crosscutting/security/rbac_resolver.py`)
- User administration: create/list/update, role assignment, lock/unlock, session revocation (`rag/api/routers/admin_users.py`)
- Admin change audit trail hooked into every RBAC/user mutation (`rag/crosscutting/security/audit_events.py`)

### Document Management & Ingestion
- Async upload → Celery ingestion job → job-status polling (`rag/api/routers/documents.py`)
- Logical Document vs. Document Version model: stable metadata/lifecycle entity vs. individual ingested files (`rag/domain/document_lifecycle.py`)
- Content-hash (SHA-256) exact-duplicate detection, skipping re-ingestion of identical files
- Automatic version supersession when a file with the same filename/identity is re-uploaded
- Source-connector identity resolution (`filesystem:`, `connector:`, `manual:`) so repeat ingestions tie into one logical document
- Version activation/deactivation, metadata editing, page-render preview (`GET /documents/{id}/render`)
- **Metadata obligation policy** — deterministic, admin-configurable per-field/per-department "required metadata" rules; documents missing required fields are quarantined rather than silently ingested (`rag/domain/metadata_policy.py`)
- Document source/connector administration, ingestion job listing, and quarantine queue review (`rag/api/routers/admin_sources.py`)
- Per-user queued-ingestion cap (default 5 concurrent) and 100 MB max upload size

### RAG / Knowledge Graph / Chat
- Full 18-node LangGraph query pipeline — see [Query Pipeline](#query-pipeline)
- Full 3-node LangGraph ingestion pipeline — see [Ingestion Pipeline](#ingestion-pipeline)
- Hybrid retrieval: dense vector search (Qdrant, `BAAI/bge-m3`), sparse/BM25 search (`Qdrant/bm25`), and **knowledge-graph traversal** (Neo4j), fused via Reciprocal Rank Fusion
- **Knowledge Graph** (optional, `BUILD_GRAPH=true`): LLM-based open extraction of entities, relations, and decision rules from each ingested document, stored in Neo4j and traversed (1–2 hops) at query time to select relevant chunks — see [Knowledge Graph](#knowledge-graph) below
- **HyDE** (Hypothetical Document Embeddings) — optional, triggered when top-retrieval confidence is low
- Cross-encoder reranking (`BAAI/bge-reranker-v2-m3`)
- **Answerability guardrail** — classifies every question as answerable / assumption / clarification / unanswerable before generating, declining or asking for clarification instead of fabricating
- **Deterministic resolver + math engine** — computes derived answers (e.g. salary progression) from extracted rules rather than trusting the LLM to compute them, with temporal and structural-coherence guards against stale or self-contradictory table data
- Multi-layer caching (in-process, Redis cross-session answer cache, query-transform cache, embedding cache) — see [Performance](#performance)
- Deterministic, template-first conversation contextualization (regex/history reconstruction) with LLM rewrite only as a fallback
- Citation resolution to document title, version, page, and on-page bounding-box region for source highlighting
- Conversations with lifecycle states, legal hold, and GDPR-style erasure requests (`rag/api/routers/conversations.py`)
- Standalone document search endpoint separate from chat (`POST /search`)

### Rules & Business Logic
Three distinct mechanisms cover what's often called a "rules engine" — see [Knowledge Graph](#knowledge-graph) for detail:
- **Metadata obligation policy** — deterministic governance rules for required document metadata (`rag/domain/metadata_policy.py`)
- **Extracted decision rules** — LLM-extracted domain rules (thresholds, mappings, formulas, eligibility, deadlines) from document content, embedded and retrievable, and consumed by the deterministic resolver (`rag/capabilities/extract.py`, `rag/capabilities/resolve.py`, `rag/capabilities/math_engine.py`)
- **RBAC configuration** — the authorization rule store (who can do what), resolved per-request (`rag/infra/stores/sql/models.py`, `rag/crosscutting/security/rbac_resolver.py`)

### Security & Guardrails
- ACL enforcement (optional, master switch) with default-deny semantics and post-retrieval live re-check to close sync-lag windows (`rag/crosscutting/security/acl.py`)
- Retrieval audit logging (hashed queries, returned/denied chunk IDs) to `data/audit/retrieval_audit.jsonl`
- Hash-chained, tamper-evident audit log with chain verification endpoint (`GET /admin/audit/verify`)
- Rate limiting (per-user, falling back to per-IP), Redis-backed, fails open on Redis outage
- Global cap on in-flight LLM generations and per-user ingestion queue caps
- Conversation lifecycle gate blocking actions on soft-deleted/purged conversations before pipeline work starts

### Administration & Licensing
- Admin panel surfaces for RBAC, users, sources/connectors, ingestion jobs, quarantine, and audit
- Licensing strategy scaffolding for tiered Free/Professional/Enterprise plans — **not yet implemented**, see [Licensing Strategy](#licensing-strategy)

### Observability & Operations
- Custom lightweight tracing over a fixed span taxonomy (embedding, retrieval, fusion, reranking, extraction, generation) persisted to a trace store (`rag/crosscutting/observability/tracing.py`)
- Optional GlitchTip (self-hosted Sentry-compatible) error tracking; Prometheus metrics and Grafana dashboards
- Encrypted, retention-pruned backup/restore of every data store (Postgres, Neo4j, Qdrant, SQLite, audit log) (`rag/backup/`)
- Ed25519-signed, hash-verified offline update bundles for the air-gapped installer/updater (`rag/update/bundle_signing.py`)

### Multi-tenancy & Scoping
- `tenant_id` threaded through context, ACL, and audit — enforced only when ACL enforcement is enabled; single-tenant (`default`) otherwise
- Department-scoped access control via the RBAC Department/AccessLevel tables

## Architecture Overview
```mermaid
graph TD;
    A[Frontend] --> B[Backend API];
    B --> C[Business Logic];
    C --> D[AI Pipeline];
    D --> E[Storage];
    E --> F[Monitoring];
    F --> G[Authentication];
    G --> H[Authorization];
    H --> I[Vector Database];
    I --> J[LLM Providers];
```
| Component | Description |
|-----------|-------------|
| Frontend | Next.js 14 app (`ui/`) — chat UI, document management, admin panel. |
| Backend API | FastAPI app (`rag/api/main.py`), routers under `rag/api/routers/` (auth, admin_rbac, admin_sources, admin_users, admin_audit, conversations, documents, search). |
| Business Logic | Domain/capability layer under `rag/domain/` and `rag/capabilities/` (search, document lifecycle, RBAC resolution). |
| AI Pipeline | Two LangGraph graphs: ingestion (`rag/graphs/ingestion.py`) and query (`rag/graphs/query.py`), run via Celery workers. |
| Storage | Postgres (users/RBAC/sessions), Neo4j (knowledge graph), Qdrant (vectors), Redis (caching), SQLite (document/chunk metadata + LangGraph checkpoints). |
| Monitoring | Prometheus + `prometheus-fastapi-instrumentator` (`/metrics`), Grafana dashboards, GlitchTip (self-hosted Sentry-compatible error tracking), `node_exporter`. |
| Authentication | JWT access/refresh tokens (`rag/crosscutting/security/tokens.py`), Argon2 password hashing, TOTP-based MFA (`pyotp`), login lockout after repeated failures. |
| Authorization | RBAC resolved per-request from Postgres (`rag/crosscutting/security/rbac_resolver.py`): roles → permissions + access-levels, scoped by department/document-type. |
| Vector Database | Qdrant, storing dense (`BAAI/bge-m3`) and sparse (`Qdrant/bm25`) embeddings for hybrid retrieval. |
| LLM Providers | Ollama (default) and vLLM (OpenAI-compatible endpoint), selected via `llm_backend` in configuration. |

## Technology Stack
### Frontend
| Library | Version | Purpose |
|---------|---------|---------|
| clsx | ^2.1.1 | Utility for conditional class names |
| lucide-react | ^0.408.0 | Icon library for React |
| next | 14.2.5 | React framework for server-side rendering |
| react | ^18.3.1 | JavaScript library for building user interfaces |
| react-dom | ^18.3.1 | Entry point for DOM-related rendering |
| tailwind-merge | ^2.4.0 | Utility for merging Tailwind CSS classes |

### Backend
| Library | Version | Purpose |
|---------|---------|---------|
| alembic | >=1.18.5 | Database migration tool for SQLAlchemy |
| argon2-cffi | >=25.1.0 | Password hashing library |
| celery | >=5.4 | Distributed task queue |
| cryptography | >=49.0.0 | Cryptographic recipes and primitives |
| fastapi | >=0.138.2 | Fast web framework for building APIs |
| fastembed | >=0.8.0 | Fast embedding library |
| flagembedding | >=1.4.0 | Library for flag embeddings |
| gradio | >=6.19.0 | Library for creating UIs for machine learning models |
| langchain-core | >=1.4.8 | Core library for LangChain |
| langchain-google-vertexai | >=3.2.4 | LangChain integration for Google Vertex AI |
| langchain-ollama | >=1.1.0 | LangChain integration for Ollama |
| langchain-openai | >=1.3.3 | LangChain integration for OpenAI |
| langgraph | >=1.2.6 | Library for graph-based language models |
| langgraph-checkpoint-sqlite | >=3.1.0 | SQLite checkpointing for LangGraph |
| neo4j | >=6.2.0 | Graph database |
| prometheus-client | >=0.21.0 | Prometheus client for Python |
| prometheus-fastapi-instrumentator | >=7.0.0 | Instrumentation for FastAPI applications |
| psycopg[binary] | >=3.3.4 | PostgreSQL adapter for Python |
| pydantic-settings | >=2.14.2 | Settings management for Pydantic |
| pyjwt[crypto] | >=2.13.0 | JSON Web Token implementation |
| psutil | >=7.0 | Process and system utilities |
| pyotp | >=2.10.0 | One-time password library |
| python-dotenv | >=1.2.2 | Load environment variables from .env files |
| qdrant-client | >=1.18.0 | Client for Qdrant vector database |
| qrcode[pil] | >=8.2 | QR code generation library |
| ragas | ==0.2.12 | RAG library |
| redis | >=5.0 | Redis client for Python |
| sentry-sdk | >=1.40.0 | Sentry SDK for error tracking |
| slowapi | | Rate limiting for FastAPI |
| sqlalchemy | >=2.0.51 | SQL toolkit and Object-Relational Mapping (ORM) |
| structlog | | Structured logging for Python |
| uvicorn[standard] | >=0.49.0 | ASGI server for FastAPI |

### AI / LLM
| Library | Purpose |
|---------|---------|
| langchain-ollama | Default local LLM backend (`llm_backend=ollama`), models pulled via Ollama. |
| langchain-openai / langchain-google-vertexai | Present as dependencies for future provider support; only `ollama` and `vllm` are wired as selectable `llm_backend` values today. |
| langgraph | Powers the ingestion and query graphs (`rag/graphs/ingestion.py`, `rag/graphs/query.py`). |
| langgraph-checkpoint-sqlite | Persists LangGraph state/checkpoints to SQLite. |

### RAG
| Library | Purpose |
|---------|---------|
| fastembed | Dense embeddings (`BAAI/bge-m3`) used at ingestion and query time. |
| flagembedding | Sparse embeddings (`Qdrant/bm25`) and cross-encoder reranking (`BAAI/bge-reranker-v2-m3`). |
| qdrant-client | Vector store client for hybrid dense+sparse retrieval (`rag/infra/stores/vector_store.py`). |
| neo4j | Graph store and entity/relationship extraction for graph-augmented retrieval (`rag/infra/stores/graph_store.py`, `rag/graph/extraction.py`). |
| ragas | Offline RAG evaluation (faithfulness, answer relevance, etc.) used in `eval/` against a golden query set. |

### Databases
| Database | Purpose |
|----------|---------|
| PostgreSQL | Users, RBAC (roles/permissions/access-levels), sessions. |
| Neo4j | Knowledge graph store for graph-based retrieval. |
| Qdrant | Vector store for dense and sparse embeddings. |
| Redis | Caching (query transform, embeddings, answers) and Celery broker/backend. |
| SQLite | Document/chunk metadata store and LangGraph checkpoint storage. |

### Storage
| Component | Purpose |
|-----------|---------|
| `./data` bind mount | Persists all databases, Qdrant data, uploaded documents, audit logs — never baked into a Docker image. |
| `hf_models` | Cached Hugging Face model weights (embeddings, reranker) shared across containers. |

### Security
| Library | Purpose |
|---------|---------|
| argon2-cffi | Password hashing (`rag/crosscutting/security/password.py`). |
| pyjwt[crypto] | JWT access/refresh token issuance and verification (`rag/crosscutting/security/tokens.py`). |
| pyotp / qrcode[pil] | TOTP-based multi-factor authentication and QR enrollment codes (`rag/crosscutting/security/mfa.py`). |
| cryptography | Key management / data-encryption-key wrapping (`rag/crosscutting/security/keystore.py`). |
| slowapi | Rate limiting for FastAPI endpoints. |

### Infrastructure
| Tool | Purpose |
|------|---------|
| Docker Compose | Orchestrates all services (`docker-compose.yml`): postgres, neo4j, qdrant, redis, app, worker, ui, nginx, monitoring stack. |
| Celery | Background task queue for ingestion jobs (`rag/worker/celery_app.py`). |
| Nginx | Reverse proxy / TLS termination (`nginx/`, `certs/`). |
| Alembic | PostgreSQL schema migrations (`alembic/`). |
| uv | Python package/dependency manager (`pyproject.toml`, `uv.lock`). |

### Observability
| Tool | Purpose |
|------|---------|
| prometheus-client / prometheus-fastapi-instrumentator | Exposes app metrics at `/metrics` (`rag/api/main.py`, `rag/observability/queue_metrics.py`). |
| Prometheus + Grafana | Metrics scraping and dashboards (`prometheus.yml`, `grafana/`). |
| GlitchTip (sentry-sdk client) | Self-hosted, Sentry-compatible error tracking (`rag/api/main.py`, `rag/bootstrap/glitchtip_db.py`, `rag/worker/celery_app.py`). |
| structlog | Structured application logging (`rag/observability/logging_config.py`). |
| node_exporter | Host-level metrics for Prometheus. |

### Development Tools
| Tool | Purpose |
|------|---------|
| pytest | Unit and integration test runner (`tests/`, `httpx`, `fakeredis` for test doubles). |
| uv | Dependency resolution and virtualenv management. |
| Docker / Docker Compose | Local dev environment and image builds. |
| eval scripts (`eval/`) | RAGAS-based offline evaluation and A/B comparison of embeddings/extraction. |

## Installation
### Quick Start (recommended)
The repository ships a guided installer that handles secrets generation, `.env` setup, and bringing up the full Docker Compose stack:
```bash
python install.py
```
This generates required secrets (`generate_secrets.py`), starts Postgres/Neo4j/Qdrant/Redis/app/worker/ui via `docker compose pull` + `up -d` (pulling published images from GHCR when available, otherwise building locally), waits for Postgres to finish first-run bootstrap, and runs Alembic migrations (`alembic upgrade head`).

### Backend (local dev, without Docker)
1. Install [uv](https://docs.astral.sh/uv/).
2. `uv sync --frozen` to install Python dependencies from `pyproject.toml` / `uv.lock`.
3. Start Postgres, Neo4j, Redis, and Qdrant (locally or via `docker compose up postgres neo4j redis qdrant -d`).
4. Run migrations: `uv run alembic upgrade head`.
5. Start the API: `uv run uvicorn rag.api.main:create_app --factory --host 0.0.0.0 --port 8000`.
6. Start a worker: `uv run celery -A rag.worker.celery_app worker --loglevel=info`.

### Frontend (local dev)
```bash
cd ui
npm install
npm run dev
```
The UI expects `API_BASE_URL` to point at the running backend (defaults to `http://app:8000` inside Docker Compose).

### Environment Variables
Copy `.env.example` (if present) or let `install.py` generate a `.env` with the secrets and connection settings listed in [Configuration](#configuration) below (`database_url`, `neo4j_uri`, `jwt_secret_key`, `llm_backend`, etc.).

### Database
- PostgreSQL schema is managed via Alembic (`alembic/`); `install.py` runs `alembic upgrade head` automatically after the containers are healthy.
- Neo4j and Qdrant are schema-less/auto-initialized on first use.

### Running
- Full stack: `python install.py` (first run) or `docker compose up -d` (subsequent runs).
- Update to a new release: `python update.py`.
- Roll back: `python rollback.py`.
- Back up / restore data: `python backup.py`, `python restore.py`.

### Production
- Pin `APP_VERSION` to a released tag so `docker compose pull` fetches a specific, scanned image rather than floating `latest`.
- Terminate TLS at the bundled Nginx reverse proxy (`nginx/`, `certs/`).
- Point `sentry-sdk`/GlitchTip and Prometheus at persistent storage/alerting for production monitoring.

## Docker
### Published Images vs. Local Build
The `app`, `worker`, and `ui` services in `docker-compose.yml` each declare **both** an `image:` and a `build:` key:

```yaml
image: ghcr.io/ferid1088/aegis-assistant-app:${APP_VERSION:-latest}
build: .
```

This gives two supported ways to get running containers:

- **`docker compose pull`** fetches the pre-built, published image for the pinned/latest tag from GHCR — no local build tools or PyPI/npm network access required.
- **`docker compose build`** (or plain `docker compose up --build`) builds the images locally from the repository's `Dockerfile` / `ui/Dockerfile` — the path for local development or when working off an unreleased commit.

`install.py` uses this to streamline first-run setup: it calls `docker compose pull` (best-effort, failures ignored) before `docker compose up -d`, so a fresh checkout gets the ready-to-use published containers when available, and transparently falls back to a local build via `up -d`'s normal build-on-demand behavior if the pull fails (offline, private fork, no matching release tag, etc.).

Published images contain only application code and its dependencies — no user data or knowledge base. Everything under `./data`, `hf_models`, and other runtime state lives on bind mounts/volumes and is never baked into an image or pushed to the registry.

### Docker Compose
To run the application using Docker Compose:
```bash
docker compose pull   # fetch published images (optional, best-effort)
docker compose up -d --build
```
This starts all services defined in `docker-compose.yml`, building any image that wasn't pulled.

### Docker Image
To build the Docker image for the application manually, use the following command:
```bash
docker build -t rag-appliance-app .
```
This command will create a Docker image named `rag-appliance-app` based on the `Dockerfile` in the root directory. The `ui` service has its own Dockerfile at `ui/Dockerfile`.

## Hardware Requirements

**Minimum: 24 GB RAM. Recommended for a fluent single-user experience: 32 GB RAM.**

`docker-compose.yml` runs quite a few services beyond just the app: `postgres`, `pgbouncer`, `redis`, `qdrant`, `neo4j`, `worker`, `app`, `ui`, `nginx`, plus the observability stack (`prometheus`, `grafana`, `node_exporter`) and GlitchTip (`glitchtip-web`/`-worker`/`-migrate`). None of these have memory limits set, so they scale with real usage rather than a fixed cap.

The dominant cost is the `worker` service: it runs Celery with `--concurrency=2`, and each of those two forked processes independently loads the full docling (layout + table extraction) and `bge-m3` embedding models into memory during document ingestion. `app` separately loads its own copy of the embedding model (and the cross-encoder reranker, lazily, on first query) for the query path. Measured live with `docker stats` while actually ingesting a document, `worker` alone peaked at 2.5–2.8 GB; everything else combined idles around 1–1.3 GB.

Those container-level numbers alone land in the ~5–6 GB range, but that doesn't account for real-world overhead: Docker Desktop's own VM tax (especially on macOS), running the LLM natively via Ollama alongside the containers, the host OS/browser/IDE, and headroom for the reranker + an ingestion job + a chat session all running at once. Accounting for that, **24 GB is the practical floor and 32 GB is what makes the experience feel fluent** rather than tight — this matches the Starter-edition hardware spec in `docs/phase_9_Editions_and_Licensing_Starter_to_Enterprise.md` §7.

If running the LLM locally via Ollama (instead of GPU-backed vLLM), add its footprint on top of the above: `qwen2.5:7b` ≈ 5–6 GB, `qwen2.5:3b` ≈ 2–3 GB. The GPU/vLLM path doesn't change this figure, since the LLM itself lives in VRAM rather than host RAM.

## Repository Structure
```
.
├── rag/                  # Backend Python package (FastAPI app, domain logic, RAG graphs)
│   ├── api/              # FastAPI app + routers (auth, admin_rbac, documents, search, conversations, ...)
│   ├── domain/           # Domain models
│   ├── capabilities/     # Application/business logic (search, document lifecycle, ...)
│   ├── graphs/           # LangGraph ingestion and query graphs
│   ├── graph/            # Neo4j graph extraction logic
│   ├── infra/             # Store adapters (Postgres, Neo4j, Qdrant, SQLite) and model factories
│   ├── crosscutting/     # Security (auth, RBAC, MFA, encryption, rate limiting), audit
│   ├── observability/    # Metrics, structured logging
│   ├── bootstrap/        # Startup wiring (e.g. GlitchTip DB provisioning)
│   └── worker/           # Celery app and tasks
├── ui/                   # Next.js 14 frontend (app, components, lib, middleware)
├── tests/                # pytest unit and integration tests
├── eval/                 # RAGAS-based evaluation harness and golden query set
├── alembic/              # PostgreSQL schema migrations
├── docs/                 # Project documentation
├── grafana/              # Grafana dashboard provisioning
├── nginx/, certs/        # Reverse proxy and TLS configuration
├── install.py            # Guided first-run installer
├── update.py, rollback.py, backup.py, restore.py  # Lifecycle/maintenance scripts
├── run_ingest.py, run_query.py                     # CLI entry points for ingestion/query
├── build_bundle.py, sign_bundle.py                 # Release bundle build/signing
├── docker-compose.yml    # Full stack orchestration
└── prometheus.yml        # Prometheus scrape configuration
```

## Ingestion Pipeline
Implemented as a 3-node LangGraph graph in [`rag/graphs/ingestion.py`](rag/graphs/ingestion.py), run by a Celery worker for each uploaded document.
```mermaid
flowchart TD;
    A[Document Upload] --> B[Convert];
    B --> C[Chunk & Index];
    C --> D[Extract Graph Artifacts - optional];
    D --> E[Activate Version];
```
| Step | Component | Details |
|------|-----------|---------|
| **Convert** | `rag/infra/docling.py` | Computes a SHA-256 whole-file content hash first — an exact duplicate short-circuits as `skipped (duplicate)`. Resolves/creates a `LogicalDocument` from a normalized source identity (`filesystem:`, `connector:`, or `manual:`), so re-uploads of the same file chain onto one logical document as new versions; same-filename uploads mark the prior version `superseded`. Parses the PDF with Docling (`PdfPipelineOptions(generate_page_images=True, images_scale=1.5)`), exporting a full `DoclingDocument` JSON and a separate `_tables.json` of extracted tables (page, caption, column/row grid). Renders page images to PNG per page. Pages with no detected text layer log a "possibly scanned" warning (no separate OCR fallback pass is invoked in this code path). |
| **Chunk & Index** | `chunk_and_index` node | Chunks text with Docling's `HybridChunker` (max 512 tokens, merges small sibling chunks); chunks that are pure tables are skipped from the prose path to avoid duplication. Computes dense embeddings (`BAAI/bge-m3`) and sparse embeddings (`Qdrant/bm25`), upserting to Qdrant in batches of 10. **Structured table extraction** runs separately: tables are heuristically checked for genuine tabular/numeric content (e.g. German-formatted currency amounts) — qualifying tables produce both a `table_row` chunk per data cell (with normalized amounts, grade/step label parsing, e.g. `"Entgeltgruppe E12, Stufe 3: 4.609,96 €"`) and a `table_full` chunk (whole table as markdown) for LLM-context readability. Each chunk stores heading path, page numbers, and bounding boxes for later citation highlighting. |
| **Extract Graph Artifacts** *(optional, `BUILD_GRAPH=true`)* | `rag/capabilities/extract.py` (re-exported via `rag/graph/extraction.py`) | Re-chunks the document a second time and runs the [knowledge-graph extraction](#knowledge-graph) LLM pass per chunk (entities, relations, decision rules), writing results to Neo4j and embedding extracted rules into Qdrant as `type="rule"` chunks. |
| **Activate Version** | ingestion graph | Only after all prior steps succeed does the new document version become `INDEXED` and "current" — so a partially-processed document is never surfaced as the active version. |

Additional ingestion behaviors: a per-user cap on concurrently queued ingestion jobs (default 5), a 100 MB max upload size, and a deterministic **metadata obligation policy** (`rag/domain/metadata_policy.py`) that quarantines any document missing admin-required metadata fields (e.g. department-specific mandatory fields) instead of silently indexing it. Admins manage recurring/connector-based ingestion sources, review job status, and clear the quarantine queue via `rag/api/routers/admin_sources.py`.

## Query Pipeline
Implemented as an 18-node LangGraph graph in [`rag/graphs/query.py`](rag/graphs/query.py), checkpointed to SQLite.
```mermaid
flowchart TD;
    A[User Query] --> B[Lifecycle Gate];
    B --> C[Contextualize];
    C --> D{Cached?};
    D -->|Yes| E[Cached Response];
    D -->|No| F[Transform Query];
    F --> G[Retrieve Dense];
    F --> H[Retrieve Sparse];
    F --> I[Retrieve Graph];
    G --> J[RRF Fusion];
    H --> J;
    I --> J;
    J --> K[HyDE - conditional];
    K --> L[Rerank];
    L --> LA[Live ACL Recheck + Retrieval Audit];
    LA --> M[Answerability Guardrail];
    M -->|answerable/assumption| N[Generate];
    M -->|clarification/unanswerable| G2[Gate Response];
    N --> O[Finalize Turn];
    G2 --> O;
```
| Stage | Description |
|-------|-------------|
| Lifecycle Gate | Blocks retrieval/generation on soft-deleted/purged conversations before any pipeline work starts. |
| Contextualize | Deterministic, template-first rewrite of follow-up questions using conversation history (e.g. carrying forward a previously mentioned salary grade); falls back to an LLM rewrite only when the deterministic path can't resolve it. Normalizes the question for cache-key stability. |
| Cache check | Checks an in-process per-session cache, then a cross-session Redis answer cache (keyed on the normalized question + document filter). A hit returns immediately as `response_source="cache"`, skipping retrieval entirely. |
| Transform Query | One LLM call producing a dense-search-optimized rewrite, a sparse/BM25-oriented expansion, extracted entities, and detected language — itself Redis-cached; language detection is cross-checked against a lightweight keyword heuristic to catch LLM drift. |
| Retrieve Dense / Sparse / Graph | Run in parallel. Dense and sparse each search two query variants (raw + transformed) and self-fuse via RRF; graph retrieval extracts canonical entities from the question and traverses the [knowledge graph](#knowledge-graph) 1–2 hops to select relevant chunks (fixed relevance score, since graph hits aren't naturally ranked). All three respect the ACL/department/tenant retrieval filter. |
| RRF Fusion | Combines dense, sparse, and graph result lists via Reciprocal Rank Fusion, truncated to the top 40 candidates. |
| HyDE *(optional)* | Hypothetical Document Embeddings — triggered only when the top fused result's raw score is below a low-confidence threshold; generates a hypothetical answer passage, embeds and searches it, and re-fuses the results. |
| Rerank | Cross-encoder reranking (`BAAI/bge-reranker-v2-m3`) of the fused candidates down to the top 10. |
| Live ACL Recheck + Retrieval Audit | Re-validates access control on the final chunk set (closing any staleness window versus the vector index) and logs a hashed, tamper-evident record of the query and which chunks were returned or denied. |
| Answerability Guardrail | Classifies the question as `answerable`, `assumption`, `clarification`, or `unanswerable` given the retrieved context and any candidate computable rules; unanswerable/clarification questions are declined without ever reaching generation. |
| Generate | For explicit quantitative questions (e.g. "after N years"), first attempts a **deterministic resolver + math engine** computation from extracted rules, guarded by temporal-staleness and structural-coherence checks against the retrieved table data; otherwise falls back to standard grounded LLM generation with numbered `[n]` citation markers and an explicit instruction not to fabricate unsupported answers. |
| Finalize Turn | Appends the turn to conversation history, writes the in-process and (for non-refusal answers) Redis caches, and persists citations enriched with document title, version, page, and bounding-box region for source highlighting. |

## Knowledge Graph
The knowledge graph is an **optional** feature (`BUILD_GRAPH=true`) that augments hybrid retrieval with entity/relationship traversal, backed by Neo4j.

**Build time** (`rag/capabilities/extract.py`, run as the ingestion graph's `extract_graph_artifacts` node):
- Extraction is **LLM-based, open-vocabulary** — no spaCy/NER library is used. A separately configurable extraction model (default `qwen2.5:7b`, distinct from the main chat model) processes each chunk with the previous chunk's text prepended for cross-chunk coreference.
- Three sequential LLM calls per chunk:
  - **Entities** — name, canonical (normalized/merged) form, and a soft type from `job_title, salary_level, entgeltgruppe, organization, regulation, concept, requirement, document`.
  - **Relations** — constrained to a fixed whitelist (`eingruppiert_in`, `gehoert_zu`, `erfordert`, `monatsentgelt`, `hebt_sich_heraus_aus`, `differenz_zu`, `gilt_fuer`, `reguliert_durch`); relations referencing entities outside the chunk's extracted set are dropped.
  - **Rules** — decision rules (`threshold`, `mapping`, `formula`, `eligibility`, `deadline`, `prohibition`, `default`) with conditions, consequence, variables, scope, a verbatim source quote, and a confidence score.
- A validation layer drops malformed/hallucinated extractions before writing to the graph.
- Extracted rules are also embedded and upserted into Qdrant as `type="rule"` chunks, so they're retrievable through normal dense/sparse search in addition to the resolver path.
- **Storage**: Neo4j nodes `(:Entity {canonical, name, type, doc_ids, chunk_ids, pages, doc_version})` merged on canonical form (idempotent across re-ingestion); edges `(:Entity)-[:RELATES {type, chunk_id, confidence, doc_id, page, doc_version}]->(:Entity)`, indexed on canonical name.

**Query time** (`retrieve_graph` node in `rag/graphs/query.py`):
- An LLM call extracts canonical entity names from the user's question.
- Matched entities are traversed 1–2 hops in Neo4j (capped at 50 neighbors per source entity), with per-hop ACL filtering applied directly in the Cypher query when ACL enforcement is enabled.
- The distinct chunk IDs referenced by matching relationships are fetched from Qdrant (top 20) — graph traversal is used purely to **select which chunks to retrieve**, not to answer directly from graph structure; graph hits carry a fixed relevance score before entering RRF fusion with dense/sparse results.
- Fails silently (returns no results) if Neo4j is unreachable or no entities are extracted from the question.

### Rules & Business Logic (the "rule database")
There is no single, literally-named "rule database" — three distinct mechanisms together cover that role:
1. **Metadata obligation policy** (`rag/domain/metadata_policy.py`) — deterministic, non-LLM, admin-configurable per-field/per-department rules for which document metadata is mandatory. This is the closest analogue to a classic business-rules/compliance engine; violating documents are quarantined.
2. **Extracted decision rules** (`rag/capabilities/extract.py`, `RuleArtifact`) — LLM-extracted domain rules from document content (see Knowledge Graph above), consumed deterministically at query time by the resolver/math engine rather than left to LLM guesswork.
3. **RBAC configuration** (`rag/infra/stores/sql/models.py`, `rag/crosscutting/security/rbac_resolver.py`) — the authorization rule store (roles, permissions, access-levels, department scoping), resolved fresh on every request.

## Authentication Flow
```mermaid
sequenceDiagram
    User->>Frontend: Login
    Frontend->>Backend: Authenticate
    Backend->>Identity Provider: Validate
    Identity Provider-->>Backend: Token
    Backend-->>Frontend: JWT
    Frontend-->>User: Access Granted
```
1. User submits credentials to `/login`; the backend verifies the password hash (Argon2, `rag/crosscutting/security/password.py`).
2. If MFA is enrolled, the backend returns a short-lived MFA-pending token (300s TTL) and the client must call `/mfa/verify` with a TOTP code (`pyotp`, `rag/crosscutting/security/mfa.py`).
3. On success, the backend issues a JWT access token (900s TTL) and refresh token (14-day TTL) via `rag/crosscutting/security/tokens.py`.
4. Repeated failed attempts trigger account lockout (`rag/crosscutting/security/lockout.py`, threshold 5 / 900s duration).
5. `/refresh` exchanges a valid refresh token for a new access token; `/logout` revokes the session.

## Authorization Flow
```mermaid
graph TD;
    A[User] --> B[Role];
    B --> C[Permission];
    C --> D[Department];
    D --> E[Resource];
    E --> F[Action];
    F --> G[Decision];
```
RBAC is resolved fresh on every request (`rag/crosscutting/security/rbac_resolver.py`) — no permission caching by design. A user's roles map to permissions and access-levels through the `Role`, `RolePermission`, `RoleAccessGrant`, `AccessLevel`, and `UserRole` tables in Postgres, scoped by department and document type. A separate, finer-grained ACL layer (`rag/crosscutting/security/acl.py`) exists but its enforcement switch (`acl_enforce`) is `False` by default — it is present in code but not yet enforced.

## Document Accessibility
```mermaid
graph TD;
    A[User] --> B[Role];
    B --> C[Department];
    C --> D[Document];
    D --> E[Classification];
    E --> F[Ownership];
    F --> G[Permission];
    G --> H[Access Granted / Denied];
```
Documents carry a department, document type, and access-level. A request is authorized when the requesting user's role grants an access-level that is greater than or equal to the document's required access-level within the same department (see the RBAC Endpoints in [API Documentation](#api-documentation) for how these are administered).

## Security Layers
```mermaid
graph TD;
    A[Internet] --> B[Reverse Proxy];
    B --> C[Authentication];
    C --> D[Authorization];
    D --> E[API Validation];
    E --> F[Business Logic];
    F --> G[Guardrails];
    G --> H[RAG];
    H --> I[Database];
    I --> J[Encryption];
    J --> K[Audit Logging];
    K --> L[Monitoring];
```
- **Reverse Proxy**: Nginx terminates TLS (`nginx/`, `certs/`) in front of the API and UI.
- **Authentication**: JWT + Argon2 + TOTP MFA, with lockout after repeated failures.
- **Authorization**: Per-request RBAC resolution against Postgres.
- **API Validation**: Pydantic request/response models in FastAPI routers.
- **Guardrails**: Answerability checks in the query graph before generation.
- **RAG**: Retrieval is scoped so users only ever retrieve chunks from documents they are authorized to see.
- **Encryption**: Data-encryption-keys managed via `rag/crosscutting/security/keystore.py` (`cryptography`); MFA secrets encrypted at rest.
- **Audit Logging**: Append-only, hash-chained audit log (`rag/crosscutting/security/audit.py`), verifiable via `GET /audit/verify`.
- **Monitoring**: Prometheus metrics and GlitchTip error tracking across API and worker processes.

## Licensing Strategy
> **Status: aspirational / scaffolded only.** No tiered Free/Professional/Enterprise feature-flag system exists yet. The codebase contains an abstract `LicenseGate` interface with a `NullLicenseGate` stub (`rag/crosscutting/security/license_gate.py`) that always permits user provisioning; a comment in that file states a real implementation is planned for a future licensing phase.
```mermaid
graph TD;
    A[Free License] --> B[Professional];
    B --> C[Enterprise];
    C --> D[Feature Flags];
    D --> E[Limits];
    E --> F[Enabled Features];
```
| Feature | Free | Professional | Enterprise |
|---------|------|--------------|------------|
| *(not yet implemented — planned)* | — | — | — |

## Database Design
### PostgreSQL
- **Purpose**: User management, RBAC, and session handling.
- **Connection URL**: `postgresql+psycopg://postgres:password@localhost:5432/appliance`

### Neo4j
- **Purpose**: Graph-based data storage.
- **Connection URI**: `bolt://localhost:7687`
- **Username**: `neo4j`
- **Password**: `password`

### SQLite
- **Purpose**: Observability and document storage.
- **Observability DB Path**: `./data/observability.db`
- **Document DB Path**: `./data/documents.db`
- **Qdrant Path**: `./data/qdrant`

## API Documentation
### Authentication Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST   | /login   | Authenticates a user and returns a JWT. |
| POST   | /mfa/enroll | Enrolls a user in multi-factor authentication (MFA). |
| POST   | /mfa/verify | Verifies the MFA token. |
| POST   | /refresh | Refreshes the access token. |
| POST   | /logout | Logs out the user. |
| GET    | /me | Retrieves the current user's information. |

### Audit Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | /audit | Lists audit entries with optional filters for actor, action, and resource. |
| GET    | /audit/verify | Verifies the integrity of the audit log chain. |

### RBAC Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST   | /departments | Creates a new department. |
| GET    | /departments | Lists all departments. |
| DELETE | /departments/{department_id} | Deletes a specified department. |
| POST   | /departments/{department_id}/access-levels | Creates a new access level for a department. |
| DELETE | /access-levels/{access_level_id} | Deletes a specified access level. |
| POST   | /roles | Creates a new role. |
| GET    | /roles | Lists all roles. |
| DELETE | /roles/{role_id} | Deletes a specified role. |
| POST   | /roles/{role_id}/grants | Grants an access level to a role. |
| DELETE | /roles/{role_id}/grants/{access_level_id} | Revokes an access level from a role. |
| POST   | /document-types | Creates a new document type. |
| GET    | /document-types | Lists all document types. |
| DELETE | /document-types/{document_type_id} | Deletes a specified document type. |

### Source Management Endpoints
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | /sources | Lists all document sources. |
| POST   | /sources | Creates a new document source. |
| PATCH  | /sources/{source_id} | Updates the enabled status of a document source. |
| GET    | /ingestion/jobs | Lists all ingestion jobs. |
| GET    | /quarantine | Lists all quarantined documents. |


## Configuration
| Variable | Default | Description |
|----------|---------|-------------|
| observability_db_path | `./data/observability.db` | Path for the observability database. |
| llm_backend | `ollama` | Backend for LLM processing. |
| ollama_base_url | `http://localhost:11434` | Base URL for Ollama. |
| vllm_base_url | `http://localhost:8000/v1` | Base URL for vLLM. |
| llm_model | `qwen2.5:7b` | Model used for LLM processing. |
| max_inflight_generations | `20` | Global cap for concurrent generations. |
| llm_request_timeout_seconds | `60` | Timeout for LLM generation requests. |
| database_url | `postgresql+psycopg://postgres:password@localhost:5432/appliance` | Connection URL for PostgreSQL. |
| neo4j_uri | `bolt://localhost:7687` | Connection URI for Neo4j. |
| sqlite_path | `./data/documents.db` | Path for the SQLite document database. |
| redis_url | `""` | Connection URL for Redis. |
| jwt_secret_key | `yhzI7e9m4LMmV2bUpZuUFjg7I6WgTooqMBN-6ZiXxDA_PwMg_Xb1sDHpTPIUMX2f` | Secret key for JWT. |

## Logging
- Structured logging via `structlog` (`rag/observability/logging_config.py`), used consistently across the API (`rag/api/main.py`) and Celery worker (`rag/worker/celery_app.py`).
- Application errors and exceptions are additionally captured by the GlitchTip client (`sentry-sdk`) for aggregation and alerting, separate from the plain-text/structured logs.
- Security-relevant actions (logins, RBAC changes, document access) go through a dedicated, append-only, hash-chained audit log (`rag/crosscutting/security/audit.py`), queryable via `GET /audit` and verifiable via `GET /audit/verify` — this is distinct from general application logging.

## Monitoring
- **Metrics**: `prometheus-fastapi-instrumentator` exposes request/latency metrics at `/metrics` on the API; `rag/observability/queue_metrics.py` exposes Celery/queue depth metrics.
- **Dashboards**: Prometheus (`prometheus.yml`) scrapes the app and `node_exporter`; Grafana (`grafana/`) provides pre-provisioned dashboards.
- **Error Tracking**: GlitchTip, a self-hosted Sentry-compatible service, is provisioned automatically (`rag/bootstrap/glitchtip_db.py`) and wired into both the API and worker via `sentry-sdk`.
- **Health Checks**: Docker Compose healthchecks gate service startup ordering (e.g. Postgres/Neo4j/Qdrant must report healthy before `app`/`worker` start); `install.py` additionally polls Postgres readiness before running migrations.

## Testing
- **Unit & integration tests**: `tests/` (92+ files) covers RBAC, authentication/MFA, account lockout, session handling, document access control, backup/restore, release-bundle signing, observability, Celery workers, and API routers. Integration tests live under `tests/integration/`.
- **Test tooling**: `pytest`, with `httpx` for API client testing and `fakeredis` to avoid a real Redis dependency in unit tests.
- **RAG evaluation**: `eval/` contains a RAGAS-based harness (`run_eval.py`, `eval_report.py`, `eval_aggregation.py`) run against a golden query set (`eval/golden_set.jsonl`, `eval/table_gold.jsonl`), plus A/B comparison scripts for embeddings (`ab_embedding.py`) and extraction (`ab_extraction.py`).
- Run the full suite with:
  ```bash
  uv run pytest
  ```

## CI/CD
### Release Workflow (`.github/workflows/release.yml`)
Triggered on every tag push matching `v*`. Steps:
1. Builds the `app` image (`rag-appliance-app:release`) from the root `Dockerfile` and the `ui` image (`rag-appliance-ui:release`) from `ui/Dockerfile`.
2. Runs a blocking Trivy scan (`CRITICAL` severity) against the built images.
3. Derives the release version from the tag name (`v1.2.3` → `1.2.3`).
4. Logs in to GHCR (`ghcr.io`) using the built-in `GITHUB_TOKEN` (requires the workflow's `packages: write` permission).
5. Tags and pushes `app`, `worker`, and `ui` images to GHCR under `ghcr.io/ferid1088/aegis-assistant-<service>`, each with both the resolved version tag and `latest`. `app` and `worker` share the same build (only their compose `command:` differs), so one image is pushed under both names.
6. Builds the release bundle via `build_bundle.py`, then **signs** it (`sign_bundle.py`) using a private key written from a repository secret, immediately removed from the runner afterward.
7. Creates a GitHub Release (tag `v1.2.3`) with the signed bundle attached (`softprops/action-gh-release@v2`).

No user data or knowledge base is ever part of the Docker build context — only application code and dependencies are published.

### Local Install (`install.py`)
Runs `docker compose pull` (non-fatal on failure) before `docker compose up -d`, so a plain repository checkout pulls the ready-to-use published containers instead of requiring a local build; if the pull fails, `up -d` builds locally per the `build:` key in `docker-compose.yml`.

## Performance
- **Caching**: Redis caches query transforms, embeddings, and generated answers to avoid recomputation on repeated/similar queries (query graph's `cached_response` node).
- **Async processing**: Document ingestion runs asynchronously via Celery workers rather than blocking the upload request; ingestion jobs and quarantine status are queryable via `/ingestion/jobs` and `/quarantine`.
- **Concurrency limits**: `max_inflight_generations` caps concurrent LLM generation requests globally; `llm_request_timeout_seconds` bounds how long a single generation can run.
- **Hybrid retrieval efficiency**: Dense, sparse, and graph retrieval run in parallel branches of the query graph before RRF fusion, rather than sequentially.

## Security Considerations
- **Secrets**: Generated by `generate_secrets.py` during install and written to `.env`; never committed to the repository or baked into Docker images.
- **Passwords**: Hashed with Argon2 (`argon2-cffi`), never stored or logged in plaintext.
- **JWT**: Access tokens (900s TTL) and refresh tokens (14-day TTL) signed with `jwt_secret_key`; MFA-pending tokens are short-lived (300s) and scoped to only permit the MFA-verification step.
- **MFA**: TOTP secrets (`pyotp`) are encrypted at rest using a dedicated `mfa_encryption_key`.
- **Encryption at rest**: Data-encryption keys are managed via a keystore abstraction (`rag/crosscutting/security/keystore.py`, `cryptography`) rather than storing sensitive data unencrypted.
- **Rate limiting**: `slowapi` protects authentication and other sensitive endpoints from brute-force/abuse.
- **Audit trail**: Hash-chained audit log detects tampering; verifiable via `GET /audit/verify`.
- **Image supply chain**: Released Docker images are scanned with Trivy (CRITICAL-severity, blocking) before being pushed to GHCR (see [CI/CD](#ci-cd)).
- **Known gap**: The fine-grained ACL layer (`rag/crosscutting/security/acl.py`) exists in code but its enforcement flag (`acl_enforce`) defaults to `False` — do not rely on it for access control until enabled and verified.

## Future Roadmap
- Kubernetes support
- Single Sign-On (SSO)
- Multi-tenancy
- High Availability (HA) deployment
- Distributed ingestion
- Agent orchestration
- Additional LLM providers

## Contributing
No `CONTRIBUTING.md` exists yet in this repository. Until one is added, the working conventions observed in this codebase are:
- Install dependencies with `uv sync --frozen` and run `uv run pytest` before submitting changes.
- Add or update tests under `tests/` for backend changes; run `eval/run_eval.py` if a change affects retrieval/generation quality.
- Tag releases as `v*` to trigger the automated GHCR build/push workflow (see [CI/CD](#ci-cd)).

## License
Aegis is licensed under the MIT License. This license allows users to use, modify, and distribute the software freely, provided that the original license notice and copyright statement are included in all copies or substantial portions of the software.

## Authors
- **Maintainer**: TBD
- **Contributors**: TBD
- **Acknowledgements**: TBD
