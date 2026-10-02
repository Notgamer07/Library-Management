# System Architecture Documentation

This directory contains the canonical architectural documentation and Mermaid diagrams for the **Library Management System & Medallion Data Pipeline**.

> [!IMPORTANT]
> **Authentication and Authorization Status**:
> Authentication and authorization are **NOT implemented** in this project. There are no user login flows, session middlewares, JWT verifications, role-based access controls (RBAC), or permission guards. All endpoints, views, and dashboards (including the Admin Dashboard and built-in Django Admin) are accessible without credentials.

---

## Index of Architectural Diagrams

| Diagram File | Type | Purpose & Scope |
| :--- | :--- | :--- |
| [`system-overview.mmd`](system-overview.mmd) | `flowchart TD` | High-level system structure, major components, and typical request paths. Readable in 10–20 seconds. |
| [`request-flow.mmd`](request-flow.mmd) | `flowchart TD` | Detailed end-to-end processing flows for all user actions (Browse, Ingest, Loan Issue, Return, Admin). |
| [`data-flow.mmd`](data-flow.mmd) | `flowchart TD` | Data movement across **Landing $\rightarrow$ Bronze $\rightarrow$ Silver $\rightarrow$ Gold** pipeline layers and consumers. |
| [`deployment.mmd`](deployment.mmd) | `flowchart TD` | Docker Compose multi-container deployment, published ports, networks, and persistent volumes. |
| [`database-erd.mmd`](database-erd.mmd) | `erDiagram` | Full entity-relationship model across Landing, Bronze, and Silver/Gold database instances. |
| [`admin-flow.mmd`](admin-flow.mmd) | `flowchart TD` | Admin dashboard interactions, live metrics collection, and background pipeline subprocess supervision. |
| [`caching-sequence.mmd`](caching-sequence.mmd) | `sequenceDiagram` | Chronological request sequence for the predictive 3-page Redis caching mechanism on catalog reads. |

---

## 1. System Overview ([`system-overview.mmd`](system-overview.mmd))

### What it Documents
A clean, high-level map answering: *"What are the major parts of this project, and how does an average request move through the system?"*

### Key Components Discovered
- **Clients**: Web Browser (User/Admin) and automated REST/Benchmark clients.
- **Application Layer**:
  - **Django Web UI** (`library_django_web` on port `8080`): Server-rendered templates for book search, loans, returns, and the admin dashboard.
  - **FastAPI Async Backend** (`library_api_backend` on port `8000`): Asynchronous REST API for high-throughput write ingestion, cached reads, and Gold analytics.
- **Caching Layer**:
  - **Redis Cache** (`library_redis_cache` on port `6379`): In-memory caching for book catalog pages and active overdue loan records.
- **Decoupled Multi-Database Medallion Pipeline**:
  - **Landing Site DB** (PostgreSQL on port `5433`): Raw, untransformed JSONB ingestion buffer.
  - **Bronze DB** (PostgreSQL on port `5434`): Sanitized data lake and ingestion dead-letter audit log.
  - **Silver & Gold DB** (PostgreSQL on port `5432`): Operational 3NF normalized relational schema and aggregated Gold analytics summary views.
  - **Data Pipeline Worker** (`library_pipeline_worker`): Independent Python ETL daemon executing scheduled transformations every 90 seconds.

---

## 2. Request Flow ([`request-flow.mmd`](request-flow.mmd))

### What it Documents
How specific categories of user interactions are routed and executed through views, serializers/validation, business logic, cache, and database layers.

### Implemented Request Categories
1. **Catalog Browsing (`GET /books/` & `GET /api/v1/books`)**:
   - *Django*: Executes parameterized SQL with `ILIKE` on Silver DB; paginated in memory via Django `Paginator`.
   - *FastAPI*: Queries Redis for requested page. On hit, returns sub-millisecond cached payload with `X-Cache: HIT`. On miss, calculates total books/pages, fetches a 3-page contiguous window (Lag, Requested, Lead) from Silver DB, caches all 3 pages in Redis, and returns only the requested page with `X-Cache: MISS`.
2. **Adding Books (`POST /books/add/` & `POST /api/v1/books`)**:
   - Both paths stage raw JSON payloads into `landing_books_ingest` on the Landing DB (`source_channel='DJANGO_UI'` or `'API'`), decoupling client response latency from relational validation.
3. **Issuing Loans (`POST /add_student/` & `POST /api/v1/ingest/borrow`)**:
   - *Django*: Executes atomic PostgreSQL stored procedure `sp_issue_book(student_id, name, book_title, loan_days)` on Silver DB with row-level locks (`SELECT FOR UPDATE`), validating inventory and updating `borrow_records` and `borrowers`.
   - *FastAPI*: Stages student borrow record into `landing_borrow_ingest` on Landing DB for asynchronous batch promotion.
4. **Returning Books (`POST /return-book/` & `POST /api/v1/loans/return`)**:
   - *Django*: AJAX request triggers atomic stored procedure `sp_return_book(record_id)` on Silver DB. Automatically computes days overdue, calculates `$5.00/day` fines, updates loan status to `'RETURNED'`, and increments available inventory.
   - *FastAPI*: Stages return intent into `landing_borrow_ingest`.
5. **Viewing Due & Overdue Records (`GET /location/` & `GET /api/v1/loans/overdue`)**:
   - *Django*: Queries `borrow_records` joined with `borrowers` and `books` on Silver DB; dynamically computes days overdue.
   - *FastAPI*: Checks Redis cache `loans:overdue:all` (TTL 30s); falls back to querying Gold view `vw_gold_overdue_fines`.
6. **Admin Dashboard & Pipeline Control**:
   - *Django*: Aggregates live row counts across all 3 database instances (`get_medallion_metrics()`) and controls the background ETL worker via the thread-safe `PipelineManager`.

---

## 3. Data Flow & Medallion Pipeline ([`data-flow.mmd`](data-flow.mmd))

### What it Documents
The complete end-to-end data progression through the Medallion architecture:

```text
Data Sources (UI Forms, REST API, Benchmark Scripts)
       ↓
Landing Layer (Raw JSONB Staging Tables on Landing DB)
       ↓  [Stage 1 ETL: Hygiene Validation, Null Checks, Dead-Letter Logging]
Bronze Layer (Sanitized Data Lake & Error Audit Log on Bronze DB)
       ↓  [Stage 2 ETL: Entity Resolution, Dimension Upserts, 3NF Normalization]
Silver Layer (Operational 3NF Normalized Relational Tables on Silver DB)
       ↓  [Stage 3 ETL: Daily Rollup Aggregation via sp_refresh_gold_analytics]
Gold Layer (Aggregated KPI Materialized Tables & Business Intelligence Views)
       ↓
Consumers (Admin Dashboard, BI APIs, End-User Catalog)
```

### Transformation Details
- **Stage 1 (Landing $\rightarrow$ Bronze)**:
  - Extracts batches up to 500 records WHERE `processed_flag = FALSE`.
  - Performs data hygiene: verifies non-empty strings, `price >= 0`, `total_copies >= 0`.
  - Valid rows loaded to `bronze_books` or `bronze_borrow_records` with `is_valid = TRUE`.
  - Failed rows logged to `bronze_ingestion_errors` (Dead Letter Queue) with raw payload and exception trace.
  - Updates `processed_flag = TRUE` in Landing DB.
- **Stage 2 (Bronze $\rightarrow$ Silver 3NF)**:
  - Resolves dimension entities: checks existence of `authors`, `categories`, `publishers` by name, creating missing entities dynamically to obtain foreign keys.
  - Upserts into `books`: handles conflict on `isbn` by incrementing `total_copies` and `available_copies`.
  - Issues borrow requests via stored procedure `sp_issue_book()`.
  - Marks `promoted_to_silver = TRUE` in Bronze DB.
- **Stage 3 (Silver $\rightarrow$ Gold Analytics)**:
  - Calls `sp_refresh_gold_analytics()` to upsert daily aggregated KPI metrics into `gold_daily_kpi_summary` for `CURRENT_DATE`.
  - Dynamic Gold views query Silver 3NF tables in real time (`vw_gold_inventory_status`, `vw_gold_overdue_fines`, `vw_gold_author_popularity`).

---

## 4. Deployment & Docker Architecture ([`deployment.mmd`](deployment.mmd))

### What it Documents
The Docker Compose orchestration topology, container port exposures, persistent volumes, and inter-service dependencies.

### Containers in the Topology
1. **`library_django_web`** (`Dockerfile.django`):
   - Host Port: `8080` (Container: `8080`)
   - Development server with volume bind-mount `.:/app` for live template and view reloading.
2. **`library_api_backend`** (`Dockerfile.api`):
   - Host Port: `8000` (Container: `8000`)
   - FastAPI server with Uvicorn. Supports dev mode (`--reload`) and multi-worker benchmark mode (`--workers 4 --loop uvloop`).
3. **`library_pipeline_worker`** (`Dockerfile.api`):
   - Internal background ETL daemon. No host ports exposed. Executes scheduled Medallion cycles every 90 seconds.
4. **`library_redis_cache`** (`redis:7-alpine`):
   - Host Port: `6379` (Container: `6379`)
   - Named volume: `redis_data`
5. **`library_db_landing`** (`postgres:16-alpine`):
   - Host Port: `5433` (Container: `5432`)
   - Named volume: `landing_postgres_data`
   - Initialized via `database/schema_landing.sql`
6. **`library_db_bronze`** (`postgres:16-alpine`):
   - Host Port: `5434` (Container: `5432`)
   - Named volume: `bronze_postgres_data`
   - Initialized via `database/schema_bronze.sql`
7. **`library_db_silver`** (`postgres:16-alpine`):
   - Host Port: `5432` (Container: `5432`)
   - Named volume: `silver_postgres_data`
   - Initialized via `database/schema_silver.sql` and `database/init_users.sql`

---

## 5. Database Entity Relationships ([`database-erd.mmd`](database-erd.mmd))

### What it Documents
The schema structures across all three physical database instances, detailing primary keys, foreign keys, constraints, and audit entities.

### Schema Summary
- **Landing DB (`landing_db`)**:
  - `landing_books_ingest` (UUID PK, JSONB payload, processed flag)
  - `landing_borrow_ingest` (UUID PK, JSONB payload, processed flag)
- **Bronze DB (`bronze_db`)**:
  - `bronze_books` (UUID PK, UUID FK `ingest_id`, hygiene attributes, promotion flag)
  - `bronze_borrow_records` (UUID PK, UUID FK `ingest_id`, loan attributes, promotion flag)
  - `bronze_ingestion_errors` (UUID PK, source layer, raw JSONB, error message)
- **Silver & Gold DB (`silver_db`)**:
  - `categories` (SERIAL PK, unique name)
  - `authors` (SERIAL PK, unique name, email)
  - `publishers` (SERIAL PK, unique name, address)
  - `books` (SERIAL PK, unique ISBN, FKs to author, category, publisher, copy counters)
  - `borrowers` (SERIAL PK, unique student_id, name, status)
  - `borrow_records` (SERIAL PK, FKs to borrower and book, loan dates, status, fine amount)
  - `fine_payments` (SERIAL PK, FK to borrow_record, amount, paid timestamp)
  - `gold_daily_kpi_summary` (DATE PK, daily catalog and financial KPI totals)
  - `library_pipelinerunhistory` (SERIAL PK, execution timestamps, stage, row counts, status)

---

## 6. Admin & Management Flow ([`admin-flow.mmd`](admin-flow.mmd))

### What it Documents
How the Admin Dashboard (`/admin-dashboard/`) integrates data metrics aggregation, process supervision, and live server resource telemetry:
- **Metrics Aggregator (`get_medallion_metrics()`)**: Queries row counts across all 3 databases simultaneously (`landing_db`, `bronze_db`, `silver_db`) to show data accumulation at each tier.
- **Process Supervisor (`PipelineManager`)**:
  - Spawns `pipelines/etl_medallion.py` in a separate OS process with thread-safe `RLock` isolation.
  - Monitors output streams in real-time, parsing `STATS:<stage>:<count>` lines to calculate live transfer numbers.
  - Buffers the last 500 log lines in an in-memory deque for client polling (`/api/pipeline/status/`).
  - Persists completed and cancelled runs into `PipelineRunHistory` in Silver DB.
  - Supports non-blocking stage execution returning HTTP `202 Accepted` immediately.
  - Implements graceful cancellation via `SIGTERM`, triggering PostgreSQL transaction rollback.
- **Resource Monitor (`psutil`)**: Exposes live CPU %, Memory usage, and Disk space via `/api/resource-monitor/`.

---

## 7. Predictive 3-Page Caching ([`caching-sequence.mmd`](caching-sequence.mmd))

### What it Documents
The sequence of events when a client queries paginated books (`GET /api/v1/books?page=N&page_size=S`):
1. **Cache Check**: API checks Redis key `catalog:books:page:N:size:S`.
2. **On Cache HIT**: Returns stored JSON page payload immediately with HTTP header `X-Cache: HIT`. Latency is under 5ms.
3. **On Cache MISS**:
   - Sets HTTP header `X-Cache: MISS`.
   - Computes the 3-page contiguous window: `Lag (page-1)`, `Requested (page)`, `Lead (page+1)`. Edge cases handled: page 1 omits lag, last page omits lead.
   - Fetches all 3 pages in a single SQL query (`OFFSET ... LIMIT ...`) from Silver DB.
   - Stores all 3 pages in parallel in Redis with a 60-second TTL.
   - Returns **ONLY** the requested page payload to the client with clean business fields.
4. **Subsequent Navigation**: When the user clicks "Next" or "Previous", the page is already cached in Redis, resulting in an instant cache hit without database queries.

---

## Architectural Observations & Implementation Boundaries

1. **Decoupled Failure Domains**:
   - The user-facing backend (FastAPI and Django) and the background pipeline worker run in separate containers.
   - If the background worker fails or is terminated, user-facing reads (from Silver DB) and writes (to Landing DB) continue without downtime or degradation.
2. **Write Ingestion vs Immediate Consistency**:
   - High-throughput ingestion writes are staged asynchronously into `landing_db`.
   - Book checkout and returns via the Django UI interact directly with Silver DB through atomic stored procedures (`sp_issue_book`, `sp_return_book`) to enforce immediate consistency for walk-in transactions.
3. **Absence of Authentication / Authorization**:
   - As noted, no authentication, login, user accounts, sessions, JWT tokens, roles, or permission checks are implemented. All pages and APIs are public.
4. **Zero-Rebuild Development**:
   - The Docker Compose environment maps host volumes (`.:/app`) and uses hot-reloading servers (Uvicorn and Django development server), allowing instant code testing without running `docker compose build`.
