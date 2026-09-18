# System Architecture & Semantics Documentation

## 1. System Core Overview

The **Decoupled High-Throughput Library Management System** is engineered using an **Enterprise Medallion Data Architecture** (Landing -> Bronze -> Silver -> Gold) coupled with an **asynchronous REST API backend** (`FastAPI` + `uvloop` + `asyncpg`/`aiomysql`) and a **Redis in-memory caching layer**.

The system is decoupled into independent layers:
- **Presentation Layer**: Django Web UI (`django_web` on port `8080`) providing interactive book management, loan issuance, and AJAX return updates.
- **Asynchronous API Service**: Decoupled FastAPI backend (`api` on port `8000`) delivering sub-millisecond JSON API endpoints.
- **Data Ingestion & Medallion Pipeline**: Asynchronous staging layer (Landing -> Bronze) and background worker daemon (`pipeline_worker`) transforming raw ingested records into normalized 3NF structures and Gold analytics marts.
- **Database Infrastructure**: PostgreSQL 16 / MySQL 8.0 containing 3NF relational schemas, B-tree indexes, views, and atomic stored procedures.
- **Caching & Connection Pooling**: Redis cache container & `asyncpg` pre-allocated connection pool to handle **~1000 requests/second** on Intel i5 13th Gen with 6-8 GB RAM.

---

## 2. Medallion Layer Semantics

| Layer | Architecture Tier | Purpose & Storage Format | Concurrency & Access Policy |
| :--- | :--- | :--- | :--- |
| **Landing** | Raw Staging | `landing_books_ingest`, `landing_borrow_ingest` (JSONB raw payloads) | Ultra-fast non-blocking ingestion without validation constraints. |
| **Bronze** | Cleaned Audit Snapshot | `bronze_books`, `bronze_borrow_records`, `bronze_ingestion_errors` | Data hygiene, schema validation, error logging, and immutable audit snapshotting. |
| **Silver** | Operational 3NF OLTP | `categories`, `authors`, `publishers`, `books`, `borrowers`, `borrow_records`, `fine_payments` | Fully normalized 3NF relational schema enforcing strict foreign key constraints and atomic transactions. |
| **Gold** | OLAP Analytics Data Mart | `vw_gold_inventory_status`, `vw_gold_overdue_fines`, `vw_gold_author_popularity`, `gold_daily_kpi_summary` | Materialized & aggregated views for reporting, dashboards, and data pipelines. |

---

## 3. Transaction Isolation & Race Condition Prevention

### A. Atomic Book Issuance (`sp_issue_book`)
- **Row-Level Locking (`FOR UPDATE`)**: When a student requests a book checkout, `sp_issue_book` locks the target row in `books` with `FOR UPDATE`. Concurrent checkout requests for the same book block until the current transaction commits or rolls back, preventing negative stock race conditions (`available_copies < 0`).
- **Atomic Borrower Upsert**: Borrower registration uses `ON CONFLICT (student_id) DO UPDATE SET name = EXCLUDED.name` to prevent duplicate key violations under concurrent student additions.

### B. Atomic Book Return & Fine Calculation (`sp_return_book`)
- **Single Return Guarantee**: `sp_return_book` locks the `borrow_records` entry with `FOR UPDATE`. If `status = 'RETURNED'`, the procedure aborts atomically.
- **Stock Replenishment & Fine Calculation**: Atomically increments `books.available_copies` and computes overdue fines ($5.00/day) in a single database transaction boundary.

---

## 4. Caching & State Semantics

- **Read Cache Strategy**: Read endpoints (`/api/v1/books`, `/api/v1/loans/overdue`) query Redis before hitting the database. On hit, cached JSON is returned in <1ms.
- **Write-Driven Invalidation**: Any write action (book insertion, book deletion, loan issuance, book return) emits immediate key pattern invalidation (`catalog:books:*`, `loans:overdue:*`), ensuring zero stale data.
- **Fallback Resilience**: If Redis is offline or unreachable, the system automatically falls back to direct database execution without service disruption.
