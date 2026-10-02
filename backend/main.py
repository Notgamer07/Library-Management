import json
from contextlib import asynccontextmanager
from typing import Optional
from datetime import datetime, timezone
import httpx
from fastapi import FastAPI, HTTPException, Query, Response, Path
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.config import settings
from backend.db import db, bronze_db, silver_db, gold_db
from backend.cache import cache

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: connect DB pools and Redis cache
    await db.connect()
    await cache.connect()
    yield
    # Shutdown: close connections
    await cache.disconnect()
    await db.disconnect()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic Schemas with Strict Input Validation & Length Limits
# (Defends against JSON DoS, Payload Flooding, and Unexpected Types)

class BronzeIngestRequest(BaseModel):
    source_channel: str = Field(default="API", max_length=50, example="MOBILE_APP")
    payload: dict = Field(..., example={"title": "Clean Code", "author": "Robert Martin", "price": 45.00})

class BookCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, example="Clean Architecture")
    author: str = Field(..., min_length=1, max_length=255, example="Robert C. Martin")
    category: str = Field(default="Computer Science", max_length=100, example="Computer Science")
    publisher: str = Field(default="Prentice Hall", max_length=255, example="Prentice Hall")
    price: float = Field(..., ge=0.0, le=100000.0, example=39.99)
    total_copies: int = Field(default=1, ge=1, le=10000)
    isbn: Optional[str] = Field(default=None, max_length=30, example="978-0134494166")

class LoanIssueRequest(BaseModel):
    student_id: str = Field(..., min_length=1, max_length=50, example="STU-1001")
    borrower_name: str = Field(..., min_length=1, max_length=255, example="John Doe")
    book_title: str = Field(..., min_length=1, max_length=255, example="Clean Architecture")
    loan_days: int = Field(default=7, ge=1, le=90)

class LoanReturnRequest(BaseModel):
    record_id: int = Field(..., ge=1, example=1)

class BorrowIngestRequest(BaseModel):
    student_id: str = Field(..., min_length=1, max_length=50, example="STU-X-101")
    borrower_name: str = Field(default="Student X", min_length=1, max_length=255, example="Student X")
    book_title: str = Field(default="Clean Architecture", min_length=1, max_length=255, example="Clean Architecture")
    loan_days: int = Field(default=7, ge=1, le=90)

class BookViewRequest(BaseModel):
    book_id: int = Field(..., ge=1, example=1)
    user_identifier: Optional[str] = Field(default="ANONYMOUS", max_length=100, example="STU-1001")

# ============================================================================
# Core System Health Status Endpoint
# ============================================================================

@app.get("/health", tags=["Health"])
async def health_check():
    backend_status = "ok"

    # 1. Bronze Database status (Raw Ingestion / Writes)
    bronze_status = "ok"
    try:
        if bronze_db.pool is None:
            bronze_status = "disconnected"
        else:
            async with bronze_db.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
    except Exception:
        bronze_status = "error"

    # 2. Silver Database status (Reads / 3NF OLTP Core)
    silver_status = "ok"
    try:
        if silver_db.pool is None:
            silver_status = "disconnected"
        else:
            async with silver_db.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
    except Exception:
        silver_status = "error"

    # 3. Gold Database status (Dedicated Analytics)
    gold_status = "ok"
    try:
        if gold_db.pool is None:
            gold_status = "disconnected"
        else:
            async with gold_db.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
    except Exception:
        gold_status = "error"

    # 4. Cache server status (Redis)
    cache_status = "ok"
    try:
        if cache.client is None:
            cache_status = "disconnected"
        else:
            await cache.client.ping()
    except Exception:
        cache_status = "error"

    # 5. Web service status (Django Web UI on port 8080)
    web_status = "ok"
    try:
        web_host = "django-web" if settings.SILVER_DB_HOST == "db_silver" else "127.0.0.1"
        async with httpx.AsyncClient(timeout=httpx.Timeout(0.2, connect=0.2)) as client:
            try:
                res = await client.get(f"http://{web_host}:8080/")
                web_status = "ok" if res.status_code in [200, 301, 302, 404] else "unavailable"
            except Exception:
                web_status = "unavailable"
    except Exception:
        web_status = "unavailable"

    now_utc = datetime.now(timezone.utc)
    timestamp_str = now_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    is_overall_ok = (backend_status == "ok" and bronze_status == "ok" and silver_status == "ok" and gold_status == "ok" and cache_status == "ok")

    return {
        "status": "ok" if is_overall_ok else "degraded",
        "backend": backend_status,
        "bronze_database": bronze_status,
        "silver_database": silver_status,
        "gold_database": gold_status,
        "web": web_status,
        "cache-server": cache_status,
        "timestamp": timestamp_str
    }

# ----------------------------------------------------------------------------
# 1. BRONZE LAYER (High-Speed Raw Write Ingestion)
# ----------------------------------------------------------------------------

@app.post(f"{settings.API_V1_STR}/ingest/bronze", tags=["1. Bronze Layer (Writes)"])
@app.post(f"{settings.API_V1_STR}/ingest/landing", tags=["1. Bronze Layer (Writes)"], include_in_schema=False)
async def ingest_to_bronze(request: BronzeIngestRequest):
    """
    High-speed write endpoint staging raw payloads into Bronze DB
    using parameterized queries ($1::jsonb, $2).
    """
    query = """
        INSERT INTO bronze_books_ingest (raw_payload, source_channel)
        VALUES ($1::jsonb, $2)
        RETURNING ingest_id, received_at;
    """
    try:
        record = await bronze_db.fetch_one(query, json.dumps(request.payload), request.source_channel)
        return {
            "status": "queued",
            "ingest_id": str(record["ingest_id"]),
            "received_at": record["received_at"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bronze ingestion failed: {str(e)}")

@app.post(f"{settings.API_V1_STR}/ingest/borrow", tags=["1. Bronze Layer (Writes)"])
async def ingest_borrow(request: BorrowIngestRequest):
    """
    High-speed write endpoint staging loan requests directly into Bronze DB.
    """
    payload = {
        "action": "ISSUE",
        "student_id": request.student_id,
        "borrower_name": request.borrower_name,
        "book_title": request.book_title,
        "loan_days": request.loan_days
    }
    query = """
        INSERT INTO bronze_borrow_ingest (raw_payload, source_channel)
        VALUES ($1::jsonb, $2)
        RETURNING ingest_id, received_at;
    """
    try:
        record = await bronze_db.fetch_one(query, json.dumps(payload), "API_BORROW_INGEST")
        return {
            "status": "queued",
            "ingest_id": str(record["ingest_id"]),
            "received_at": record["received_at"],
            "borrow_record": payload
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bronze borrow ingestion failed: {str(e)}")

@app.post(f"{settings.API_V1_STR}/books", tags=["1. Bronze Layer (Writes)"])
async def create_book(book: BookCreateRequest):
    """
    CQRS Write Request: Stages book creation request into Bronze DB.
    """
    payload = {
        "title": book.title,
        "author": book.author,
        "category": book.category,
        "publisher": book.publisher,
        "price": book.price,
        "total_copies": book.total_copies,
        "isbn": book.isbn
    }
    query = """
        INSERT INTO bronze_books_ingest (raw_payload, source_channel)
        VALUES ($1::jsonb, $2)
        RETURNING ingest_id, received_at;
    """
    try:
        record = await bronze_db.fetch_one(query, json.dumps(payload), "API_BOOK_CREATE")
        await cache.invalidate("catalog:books:*")
        return {
            "status": "queued",
            "message": "Write request received. Book creation staged in Bronze Database.",
            "ingest_id": str(record["ingest_id"]),
            "received_at": record["received_at"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bronze book creation write failed: {str(e)}")

@app.post(f"{settings.API_V1_STR}/loans/issue", tags=["1. Bronze Layer (Writes)"])
async def issue_book(loan: LoanIssueRequest):
    """
    CQRS Write Request: Stages loan issue request into Bronze DB.
    """
    payload = {
        "action": "ISSUE",
        "student_id": loan.student_id,
        "borrower_name": loan.borrower_name,
        "book_title": loan.book_title,
        "loan_days": loan.loan_days
    }
    query = """
        INSERT INTO bronze_borrow_ingest (raw_payload, source_channel)
        VALUES ($1::jsonb, $2)
        RETURNING ingest_id, received_at;
    """
    try:
        record = await bronze_db.fetch_one(query, json.dumps(payload), "API_LOAN_ISSUE")
        await cache.invalidate("catalog:books:*")
        await cache.invalidate("loans:overdue:*")
        return {
            "status": "queued",
            "message": "Write request received. Loan issue staged in Bronze Database.",
            "ingest_id": str(record["ingest_id"]),
            "received_at": record["received_at"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bronze loan write failed: {str(e)}")

@app.post(f"{settings.API_V1_STR}/loans/return", tags=["1. Bronze Layer (Writes)"])
async def return_book(payload: LoanReturnRequest):
    """
    CQRS Write Request: Stages loan return request into Bronze DB.
    """
    data = {
        "action": "RETURN",
        "record_id": payload.record_id
    }
    query = """
        INSERT INTO bronze_borrow_ingest (raw_payload, source_channel)
        VALUES ($1::jsonb, $2)
        RETURNING ingest_id, received_at;
    """
    try:
        record = await bronze_db.fetch_one(query, json.dumps(data), "API_LOAN_RETURN")
        await cache.invalidate("catalog:books:*")
        await cache.invalidate("loans:overdue:*")
        return {
            "status": "queued",
            "message": "Write request received. Loan return staged in Bronze Database.",
            "ingest_id": str(record["ingest_id"]),
            "received_at": record["received_at"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bronze loan return write failed: {str(e)}")

@app.post(f"{settings.API_V1_STR}/books/{{book_id}}/view", tags=["1. Bronze Layer (Writes)"])
async def track_book_view(book_id: int = Path(..., ge=1), user_identifier: str = Query(default="ANONYMOUS", max_length=100)):
    """
    Tracks a book view event by staging it into Bronze DB.
    """
    payload = {
        "book_id": book_id,
        "user_identifier": user_identifier
    }
    query = """
        INSERT INTO bronze_book_views_ingest (raw_payload, source_channel)
        VALUES ($1::jsonb, $2)
        RETURNING view_id, received_at;
    """
    try:
        record = await bronze_db.fetch_one(query, json.dumps(payload), "API_BOOK_VIEW")
        return {
            "status": "queued",
            "view_id": str(record["view_id"]),
            "received_at": record["received_at"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Book view tracking failed: {str(e)}")

# ----------------------------------------------------------------------------
# 2. SILVER LAYER (Catalog & Inventory Reads with Redis Caching)
# ----------------------------------------------------------------------------

@app.get(f"{settings.API_V1_STR}/books", tags=["2. Silver Layer (Catalog Reads)"])
async def list_books(
    response: Response,
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page")
):
    """
    Get paginated book catalog from Silver Database with predictive 3-page Redis caching.
    """
    cache_key = f"catalog:books:page:{page}:size:{page_size}"
    cached_raw = await cache.get_raw(cache_key)
    if cached_raw is not None:
        return Response(
            content=cached_raw,
            media_type="application/json",
            headers={"X-Cache": "HIT", "X-Cache-Key": cache_key}
        )

    # Cache MISS
    response.headers["X-Cache"] = "MISS"
    response.headers["X-Cache-Key"] = cache_key
    count_key = "catalog:books:count"
    total_books = await cache.get(count_key)
    if total_books is None:
        try:
            count_row = await silver_db.fetch_one("SELECT COUNT(*) AS total FROM books;")
            total_books = int(count_row["total"]) if count_row else 0
            await cache.set(count_key, total_books, ttl=settings.CACHE_TTL_SECONDS)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Database count query failed: {str(e)}")
    else:
        total_books = int(total_books)

    total_pages = max(1, (total_books + page_size - 1) // page_size) if total_books > 0 else 1

    pages_to_fetch = []
    if page > 1 and (page - 1) <= total_pages:
        pages_to_fetch.append(page - 1)
    if page <= total_pages:
        pages_to_fetch.append(page)
    if page < total_pages:
        pages_to_fetch.append(page + 1)
    if not pages_to_fetch:
        pages_to_fetch = [page]

    min_p = min(pages_to_fetch)
    max_p = max(pages_to_fetch)

    if total_books == 0 or min_p > total_pages:
        all_rows = []
    else:
        offset = (min_p - 1) * page_size
        limit = (max_p - min_p + 1) * page_size

        query = """
            SELECT 
                b.book_id,
                b.title,
                a.name AS author,
                c.name AS category,
                p.name AS publisher,
                b.price,
                b.total_copies,
                b.available_copies,
                b.isbn
            FROM books b
            JOIN authors a ON b.author_id = a.author_id
            JOIN categories c ON b.category_id = c.category_id
            JOIN publishers p ON b.publisher_id = p.publisher_id
            ORDER BY b.book_id DESC
            OFFSET $1 LIMIT $2;
        """
        try:
            all_rows = await silver_db.fetch_all(query, offset, limit)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")

    req_page_payload = None

    for p in pages_to_fetch:
        if p > total_pages or total_books == 0:
            page_items = []
        else:
            start_idx = (p - min_p) * page_size
            end_idx = start_idx + page_size
            page_items = all_rows[start_idx:end_idx]

        page_payload = {
            "page": p,
            "page_size": page_size,
            "total_pages": total_pages,
            "total_books": total_books,
            "data": page_items
        }

        pk = f"catalog:books:page:{p}:size:{page_size}"
        await cache.set(pk, page_payload, ttl=settings.CACHE_TTL_SECONDS)

        if p == page:
            req_page_payload = page_payload

    if req_page_payload is None:
        req_page_payload = {
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "total_books": total_books,
            "data": []
        }

    return req_page_payload

@app.delete(f"{settings.API_V1_STR}/books/{{book_id}}", tags=["2. Silver Layer (Catalog Reads)"])
async def delete_book(book_id: int):
    """Delete a book from Silver and invalidate cache."""
    try:
        await silver_db.execute("DELETE FROM books WHERE book_id = $1", book_id)
        await cache.invalidate("catalog:books:*")
        return {"status": "success", "message": f"Book {book_id} deleted from Silver database."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")

@app.get(f"{settings.API_V1_STR}/loans/overdue", tags=["2. Silver Layer (Catalog Reads)"])
async def list_overdue_loans():
    """Fetch active overdue loans from Silver Database."""
    cache_key = "loans:overdue:all"
    cached = await cache.get(cache_key)
    if cached is not None:
        return {"source": "cache", "data": cached}

    query = """
        SELECT 
            br.record_id,
            bw.student_id,
            bw.name AS borrower_name,
            bk.title AS book_title,
            br.borrowed_at,
            br.due_date,
            br.returned_at,
            br.status,
            GREATEST(0, EXTRACT(DAY FROM (CURRENT_TIMESTAMP - br.due_date)))::INT AS days_overdue,
            (GREATEST(0, EXTRACT(DAY FROM (CURRENT_TIMESTAMP - br.due_date)))::INT * 5.00)::NUMERIC(8,2) AS calculated_fine
        FROM borrow_records br
        JOIN borrowers bw ON br.borrower_id = bw.borrower_id
        JOIN books bk ON br.book_id = bk.book_id
        WHERE br.due_date < CURRENT_TIMESTAMP AND br.status IN ('BORROWED', 'OVERDUE');
    """
    records = await silver_db.fetch_all(query)
    await cache.set(cache_key, records, ttl=30)
    return {"source": "database", "data": records}

# ----------------------------------------------------------------------------
# 3. GOLD LAYER (Dedicated Analytical Aggregations from Gold DB)
# ----------------------------------------------------------------------------

@app.get(f"{settings.API_V1_STR}/analytics/gold-summary", tags=["3. Gold Layer Analytics"])
async def get_gold_analytics():
    """
    Retrieve day-wise and month-wise book views and loans/returns from dedicated Gold DB.
    """
    try:
        daily_views = await gold_db.fetch_all(
            "SELECT * FROM gold_book_views_daily ORDER BY summary_date DESC, total_views DESC LIMIT 10;"
        )
        monthly_views = await gold_db.fetch_all(
            "SELECT * FROM gold_book_views_monthly ORDER BY summary_year DESC, summary_month DESC, total_views DESC LIMIT 10;"
        )
        daily_loans = await gold_db.fetch_all(
            "SELECT * FROM gold_loans_returns_daily ORDER BY summary_date DESC LIMIT 14;"
        )
        monthly_loans = await gold_db.fetch_all(
            "SELECT * FROM gold_loans_returns_monthly ORDER BY summary_year DESC, summary_month DESC LIMIT 12;"
        )

        return {
            "gold_book_views_daily": daily_views,
            "gold_book_views_monthly": monthly_views,
            "gold_loans_returns_daily": daily_loans,
            "gold_loans_returns_monthly": monthly_loans
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gold analytics query failed: {str(e)}")
