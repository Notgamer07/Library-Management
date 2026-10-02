# Execution Workflows & System Processes

## 1. High-Throughput Request Handling Workflow (~1000 req/sec Target)

```
       Client Request
             │
             ▼
     ┌───────────────┐
     │ FastAPI App   │
     └───────┬───────┘
             │
     Is Read Operation?
      ├── YES ──► Check Redis Cache Key 
      │                │
      │                ├── Cache HIT ──► Return Cached JSON (< 1ms)
      │                │
      │                └── Cache MISS ──► Acquire Async Connection from Pool
      │                                         │
      │                                         ▼
      │                                  Execute Indexed SQL
      │                                         │
      │                                         ▼
      │                                  Populate Redis Cache (TTL 60s)
      │                                         │
      │                                         ▼
      │                                  Return JSON Response
      │
      └── NO ───► Acquire Connection from Pool
                       │
                       ▼
                Execute Atomic Stored Procedure (Row-Level Locking)
                       │
                       ▼
                Emit Write-Driven Redis Cache Invalidation
                       │
                       ▼
                Return Transaction Status JSON
```

---

## 2. Book Checkout Workflow (`sp_issue_book`)

1. **Client Submission**: User submits Student Name, Roll Number / Student ID, and Book Title via UI or API (`/api/v1/loans/issue`).
2. **Atomic Procedure Execution**:
   - `sp_issue_book` checks if borrower exists; if not, performs atomic `INSERT INTO borrowers ... ON CONFLICT DO UPDATE`.
   - Acquires row-level lock (`FOR UPDATE`) on matching book row in `books` table.
   - Checks `available_copies > 0`.
     * If out of stock, aborts transaction and returns `success = FALSE, message = "Book is currently out of stock."`.
   - Decrements `available_copies` by 1.
   - Computes `due_date = CURRENT_TIMESTAMP + INTERVAL '7 days'`.
   - Inserts record into `borrow_records` with `status = 'BORROWED'`.
3. **State Sync & Response**:
   - Flushes Redis catalog and overdue cache keys.
   - Returns success payload with `record_id` and `due_date`.

---

## 3. Real-Time Book Return Workflow (`sp_return_book`)

1. **Client Interaction**: User hovers over overdue row in `Due Books` page (`/location/`) and clicks **Return** button (AJAX request to `/return-book/` or `/api/v1/loans/return`).
2. **Atomic Return Execution**:
   - Calls `sp_return_book(record_id)`.
   - Acquires row lock (`FOR UPDATE`) on `borrow_records`.
   - Verifies `status != 'RETURNED'`.
   - Checks `returned_at > due_date`. If overdue, calculates fine at **$5.00 per day overdue**.
   - Updates `borrow_records`: sets `returned_at = CURRENT_TIMESTAMP`, `status = 'RETURNED'`, `fine_amount = calculated_fine`.
   - Atomically increments `books.available_copies` by 1.
3. **AJAX UI Update**:
   - Returns JSON payload with `returned_date` and `fine_amount`.
   - Frontend updates row status to returned in real-time without reloading the page.

---

## 4. Medallion ETL Data Pipeline Workflow (`pipeline/etl_medallion.py`)

```
   Raw API / Web Payload
            │
            ▼
┌─────────────────────────┐
│ 1. LANDING LAYER        │  Raw JSON payloads inserted asynchronously into
│ (landing_books_ingest)  │  landing_books_ingest table (processed_flag = FALSE).
└───────────┬─────────────┘
            │
            ▼ (ETL Worker Daemon every 90s)
┌─────────────────────────┐
│ 2. BRONZE LAYER         │  Pipeline sanitizes raw json, validates data hygiene,
│ (bronze_books)          │  logs invalid rows to bronze_ingestion_errors.
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ 3. SILVER LAYER         │  Entity resolution resolves/creates Author, Category, 
│ (books, authors, 3NF)   │  Publisher IDs; upserts into normalized Silver tables.
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ 4. GOLD LAYER           │  Executes sp_refresh_gold_analytics() to update
│ (gold_daily_kpi_summary)│  daily KPI summaries and business intelligence views.
└─────────────────────────┘
```
