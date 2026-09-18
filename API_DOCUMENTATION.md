# JTG Library Management System - API Documentation

A comprehensive technical reference for the Decoupled High-Throughput Library Management System REST API and internal administrative endpoints.

The JTG Library Management System utilizes a **high-throughput, decoupled architecture** built on the **Medallion Data Pattern** (Landing &rarr; Bronze &rarr; Silver &rarr; Gold):

- **FastAPI Async Engine** (http://localhost:8000): High-speed, non-blocking asynchronous REST API designed for high-concurrency workloads (~1000 req/sec), featuring  syncpg connection pooling and Redis sub-millisecond in-memory caching.
- **Django Web UI & Admin Controller** (http://localhost:8080): Full-featured administrative control center, operational UI, and pipeline orchestrator.

Interactive Swagger/OpenAPI documentation is available at http://localhost:8000/docs (or Redoc at http://localhost:8000/redoc).

---

## Base URLs & Headers

| Service | Port | Base URL | Content-Type |
| :--- | :--- | :--- | :--- |
| **FastAPI Backend** | 8000 | http://localhost:8000/api/v1 | pplication/json |
| **Django Web App** | 8080 | http://localhost:8080 | pplication/x-www-form-urlencoded / pplication/json |

---

## 1. FastAPI Endpoints (:8000)

### 1.1 Health Check

#### GET /health
Verifies backend service health, database connection pool status, and Redis cache responsiveness.

- **URL**: http://localhost:8000/health
- **Method**: GET
- **Headers**: None required
- **Parameters**: None

##### Example Request:
` ash
curl -X GET http://localhost:8000/health
`

##### Example Response (200 OK):
`json
{
  "status": "ok",
  "backend": "ok",
  "database": "ok",
  "web": "ok",
  "cache-server": "ok",
  "timestamp": "2026-09-18T11:45:00.123Z"
}
`

---

### 1.2 Landing Layer Ingestion

#### POST /api/v1/ingest/landing
High-speed asynchronous staging endpoint that accepts raw book ingestion payloads into the Landing layer without relational locks or validation constraints.

- **URL**: http://localhost:8000/api/v1/ingest/landing
- **Method**: POST
- **Headers**: Content-Type: application/json

##### Request Body Schema:
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| source_channel | string | No (default: "API") | Identifier for the origin source (e.g., "MOBILE_APP", "BATCH", "PARTNER"). |
| payload | object | Yes | Raw data dictionary containing book attributes (	itle, uthor, price, 	otal_copies, isbn, category, publisher). |

##### Example Request:
`ash
curl -X POST http://localhost:8000/api/v1/ingest/landing \
  -H "Content-Type: application/json" \
  -d '{
    "source_channel": "API_CLIENT",
    "payload": {
      "title": "Designing Data-Intensive Applications",
      "author": "Martin Kleppmann",
      "category": "Computer Science",
      "publisher": "O'\''Reilly Media",
      "price": 49.99,
      "total_copies": 10,
      "isbn": "978-1449373320"
    }
  }'
`

##### Example Response (200 OK):
`json
{
  "status": "queued",
  "ingest_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "received_at": "2026-09-18T16:00:00.000Z"
}
`

---

### 1.3 Silver Layer (Catalog & Inventory)

#### GET /api/v1/books
Returns the complete catalog of books. Results are cached in Redis (catalog:books:all) with a 60-second TTL.

- **URL**: http://localhost:8000/api/v1/books
- **Method**: GET
- **Headers**: None required

##### Example Request:
`ash
curl -X GET http://localhost:8000/api/v1/books
`

##### Example Response (200 OK):
`json
{
  "source": "cache",
  "data": [
    {
      "book_id": 1,
      "title": "Clean Architecture",
      "author": "Robert C. Martin",
      "category": "Computer Science",
      "publisher": "Prentice Hall",
      "price": 39.99,
      "total_copies": 8,
      "available_copies": 6,
      "isbn": "978-0134494166"
    }
  ]
}
`

---

#### POST /api/v1/books
Creates a new book directly in the Silver 3NF tables. Automatically resolves Author, Category, and Publisher foreign keys and invalidates the Redis catalog cache.

- **URL**: http://localhost:8000/api/v1/books
- **Method**: POST
- **Headers**: Content-Type: application/json

##### Request Body Schema:
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| 	title | string | Yes | Title of the book. |
| author | string | Yes | Name of the author. |
| category | string | No (default: "Computer Science") | Category classification. |
| publisher | string | No (default: "Prentice Hall") | Publisher name. |
| price | 
umber | Yes | Retail price (e.g., 29.99). |
| 	otal_copies | integer | No (default: 1, min: 1) | Total inventory copies. |
| isbn | string | No | Unique ISBN-10 or ISBN-13 identifier. |

##### Example Request:
`bash
curl -X POST http://localhost:8000/api/v1/books \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Refactoring",
    "author": "Martin Fowler",
    "category": "Software Engineering",
    "publisher": "Addison-Wesley",
    "price": 44.50,
    "total_copies": 5,
    "isbn": "978-0201485677"
  }'
`

##### Example Response (200 OK):
`json
{
  "status": "success",
  "message": "Book created successfully",
  "book": {
    "book_id": 42,
    "title": "Refactoring"
  }
}
`

---

#### DELETE /api/v1/books/{book_id}
Removes a book from the catalog by its primary key ID and purges Redis cache keys.

- **URL**: http://localhost:8000/api/v1/books/42
- **Method**: DELETE

##### Example Request:
`bash
curl -X DELETE http://localhost:8000/api/v1/books/42
`

##### Example Response (200 OK):
`json
{
  "status": "success",
  "message": "Book 42 deleted."
}
`

---

### 1.4 Atomic Loan Transactions

#### POST /api/v1/loans/issue
Executes PostgreSQL atomic stored procedure sp_issue_book with row-level locking (FOR UPDATE) to ensure zero inventory discrepancies under concurrent requests.

- **URL**: http://localhost:8000/api/v1/loans/issue
- **Method**: POST
- **Headers**: Content-Type: application/json

##### Request Body Schema:
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| student_id | string | Yes | Unique student registration number (e.g., "STU-2024-001"). |
| borrower_name | string | Yes | Full name of the borrower. |
| book_title | string | Yes | Title of the book to checkout. |
| loan_days | integer | No (default: 7, range: 1-30) | Loan period duration in days. |

##### Example Request:
`bash
curl -X POST http://localhost:8000/api/v1/loans/issue \
  -H "Content-Type: application/json" \
  -d '{
    "student_id": "STU-1001",
    "borrower_name": "Alice Johnson",
    "book_title": "Clean Architecture",
    "loan_days": 14
  }'
`

##### Example Response (200 OK):
`json
{
  "status": "success",
  "message": "Book issued successfully",
  "record_id": 105,
  "due_date": "2026-10-02T16:00:00.000Z"
}
`

---

#### POST /api/v1/loans/return
Executes atomic stored procedure sp_return_book. Increments book stock, timestamps the return, and calculates overdue fines (\.00/day overdue).

- **URL**: http://localhost:8000/api/v1/loans/return
- **Method**: POST
- **Headers**: Content-Type: application/json

##### Request Body Schema:
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| 
ecord_id | integer | Yes | Borrow record ID. |

##### Example Request:
`bash
curl -X POST http://localhost:8000/api/v1/loans/return \
  -H "Content-Type: application/json" \
  -d '{
    "record_id": 105
  }'
`

##### Example Response (200 OK):
`json
{
  "status": "success",
  "message": "Book returned successfully",
  "returned_at": "2026-09-18T16:15:00.000Z",
  "fine_amount": 0.0
}
`

---

#### GET /api/v1/loans/overdue
Fetches all active overdue loans from Gold view vw_gold_overdue_fines cached in Redis (30-second TTL).

- **URL**: http://localhost:8000/api/v1/loans/overdue
- **Method**: GET

##### Example Request:
`bash
curl -X GET http://localhost:8000/api/v1/loans/overdue
`

---

### 1.5 Gold Layer Analytics

#### GET /api/v1/analytics/gold-summary
Retrieves daily KPI rollups, top borrowed authors, and inventory health distribution.

- **URL**: http://localhost:8000/api/v1/analytics/gold-summary
- **Method**: GET

##### Example Request:
`bash
curl -X GET http://localhost:8000/api/v1/analytics/gold-summary
`

##### Example Response (200 OK):
`json
{
  "daily_kpis": {
    "summary_date": "2026-09-18",
    "total_books_in_catalog": 120,
    "total_copies_available": 450,
    "total_active_loans": 28,
    "total_overdue_loans": 3,
    "total_fines_accrued": 15.00,
    "total_fines_collected": 5.00
  },
  "top_authors": [
    { "author_name": "Robert C. Martin", "total_times_borrowed": 42 }
  ],
  "inventory_health": [
    { "stock_status": "IN_STOCK", "count": 115 },
    { "stock_status": "OUT_OF_STOCK", "count": 5 }
  ]
}
`

---

## 2. Django Administrative & Pipeline API (:8080)

### 2.1 Medallion Pipeline Control

#### GET /api/pipeline/status/
Returns live pipeline execution status, active running pipeline metadata, logs, and row counters across Medallion layers.

- **URL**: http://localhost:8080/api/pipeline/status/
- **Method**: GET

##### Example Request:
`bash
curl -X GET http://localhost:8080/api/pipeline/status/
`

##### Example Response (200 OK):
`json
{
  "status": "success",
  "pipeline": {
    "is_running": true,
    "status": "RUNNING",
    "pipeline_type": "landing_to_bronze",
    "pipeline_type_display": "Landing to Bronze",
    "pid": 8942,
    "started_at": "2026-09-18 16:20:00",
    "elapsed_seconds": 12,
    "logs": [
      "[16:20:00] Starting Medallion Pipeline: Landing to Bronze",
      "[16:20:01] Stage 1: 50 items promoted to Bronze, 0 error items logged."
    ],
    "active_pipelines": [
      {
        "id": 14,
        "type": "landing_to_bronze",
        "type_display": "Landing to Bronze",
        "status": "RUNNING",
        "pid": 8942,
        "started_at": "2026-09-18 16:20:00",
        "elapsed_seconds": 12
      }
    ],
    "current_stats": {
      "rows_landing_to_bronze": 50,
      "rows_bronze_to_silver": 0,
      "gold_refreshed": false
    }
  },
  "metrics": {
    "landing_unprocessed": 0,
    "landing_total": 50,
    "bronze_books": 50,
    "bronze_errors": 0,
    "silver_books": 35,
    "silver_borrowers": 12,
    "silver_active_loans": 4,
    "silver_overdue_loans": 1
  }
}
`

---

#### POST /api/pipeline/start/
Starts an isolated Medallion pipeline execution for a specific stage. The start button in the UI is automatically disabled during execution.

- **URL**: http://localhost:8080/api/pipeline/start/
- **Method**: POST
- **Headers**: Content-Type: application/x-www-form-urlencoded or pplication/json

##### Allowed pipeline_type Values:
1. landing_to_bronze: Staging validation, hygiene checks, and Bronze insert.
2. bronze_to_silver: 3NF relational normalization and catalog upsert.
3. silver_to_gold: Analytics view rollup and daily KPI refresh.

##### Example Request (Form-encoded):
`bash
curl -X POST http://localhost:8080/api/pipeline/start/ \
  -d "pipeline_type=landing_to_bronze"
`

##### Example Request (JSON):
`bash
curl -X POST http://localhost:8080/api/pipeline/start/ \
  -H "Content-Type: application/json" \
  -d '{"pipeline_type": "bronze_to_silver"}'
`

##### Example Response (200 OK):
`json
{
  "success": true,
  "message": "Pipeline 'Landing to Bronze' started successfully.",
  "pipeline": {
    "is_running": true,
    "status": "RUNNING",
    "pipeline_type": "landing_to_bronze",
    "pid": 8942
  }
}
`

---

#### POST /api/pipeline/stop/
Sends SIGTERM to the active pipeline worker subprocess. The active PostgreSQL transaction rolls back immediately and cleanly without committing partial state.

- **URL**: http://localhost:8080/api/pipeline/stop/
- **Method**: POST

##### Example Request:
`bash
curl -X POST http://localhost:8080/api/pipeline/stop/
`

##### Example Response (200 OK):
`json
{
  "success": true,
  "message": "Pipeline stopped. In-progress transactions rolled back safely.",
  "pipeline": {
    "is_running": false,
    "status": "CANCELLED"
  }
}
`

---

#### GET /api/pipeline/history/
Returns the audit trail of the last 50 pipeline runs.

- **URL**: http://localhost:8080/api/pipeline/history/
- **Method**: GET

##### Example Request:
`bash
curl -X GET http://localhost:8080/api/pipeline/history/
`

##### Example Response (200 OK):
`json
{
  "status": "success",
  "runs": [
    {
      "id": 14,
      "mode": "landing_to_bronze",
      "pipeline_type_display": "Landing to Bronze",
      "started_at": "2026-09-18T16:20:00Z",
      "ended_at": "2026-09-18T16:20:04Z",
      "duration_seconds": 4,
      "status": "COMPLETED",
      "rows_landing_to_bronze": 50,
      "rows_bronze_to_silver": 0,
      "gold_refreshed": false,
      "error_message": null
    }
  ]
}
`

---

#### GET /api/resource-monitor/
Live OS telemetry using psutil.

- **URL**: http://localhost:8080/api/resource-monitor/
- **Method**: GET

##### Example Response (200 OK):
`json
{
  "status": "success",
  "cpu": { "percent": 4.5, "count": 8 },
  "memory": { "total_mb": 16384.0, "used_mb": 8192.0, "available_mb": 8192.0, "percent": 50.0 },
  "disk": { "total_gb": 512.0, "used_gb": 256.0, "free_gb": 256.0, "percent": 50.0 },
  "db_pool": { "status": "connected", "backend": "psycopg2" },
  "pipeline": { "is_running": false, "mode": "IDLE" }
}
`

---

## 3. UI Web Routes (:8080)

| Method | Path | Description |
| :--- | :--- | :--- |
| GET | / | Home dashboard, live system telemetry cards, quick checkout form. |
| POST | /add_student/ | Home checkout form submission &rarr; executes sp_issue_book. |
| GET | /books/ | Paginated catalog table (?q=<search>, ?page=1, ?page_size=12). |
| POST | /books/add/ | Add book form submission &rarr; upserts into ooks. |
| POST | /books/delete/<id>/ | Delete book form submission. |
| GET | /location/ | Active loans and overdue borrowers table. |
| POST | /return-book/ | Book return form submission &rarr; executes sp_return_book. |
| GET | /admin-dashboard/ | Medallion Pipeline Control Center & Resource Monitor. |
