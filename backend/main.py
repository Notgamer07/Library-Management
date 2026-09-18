import json
from contextlib import asynccontextmanager
from typing import Optional, List, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from backend.config import settings
from backend.db import db
from backend.cache import cache

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: connect DB pool and Redis cache
    await db.connect()
    await cache.connect()
    yield
    # Shutdown: close connections
    await cache.disconnect()
    await db.disconnect()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
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

# ============================================================================
# Pydantic Schemas
# ============================================================================

class LandingIngestRequest(BaseModel):
    source_channel: str = Field(default="API", example="MOBILE_APP")
    payload: dict = Field(..., example={"title": "Clean Code", "author": "Robert Martin", "price": 45.00})

class BookCreateRequest(BaseModel):
    title: str = Field(..., example="Clean Architecture")
    author: str = Field(..., example="Robert C. Martin")
    category: str = Field(default="Computer Science", example="Computer Science")
    publisher: str = Field(default="Prentice Hall", example="Prentice Hall")
    price: float = Field(..., example=39.99)
    total_copies: int = Field(default=1, ge=1)
    isbn: Optional[str] = Field(default=None, example="978-0134494166")

class LoanIssueRequest(BaseModel):
    student_id: str = Field(..., example="STU-1001")
    borrower_name: str = Field(..., example="John Doe")
    book_title: str = Field(..., example="Clean Architecture")
    loan_days: int = Field(default=7, ge=1, le=30)

class LoanReturnRequest(BaseModel):
    record_id: int = Field(..., example=1)

# ============================================================================
from datetime import datetime, timezone
import httpx

# ============================================================================
# Core API Routes
# ============================================================================

@app.get("/health", tags=["Health"])
async def health_check():
    # 1. Backend API status
    backend_status = "ok"

    # 2. Database connection status
    db_status = "ok"
    try:
        if db.pool is None:
            db_status = "disconnected"
        else:
            async with db.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
    except Exception:
        db_status = "error"

    # 3. Cache server status (Redis)
    cache_status = "ok"
    try:
        if cache.client is None:
            cache_status = "disconnected"
        else:
            await cache.client.ping()
    except Exception:
        cache_status = "error"

    # 4. Web service status (Django Web UI on port 8080)
    web_status = "ok"
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            # Check container hostname first, fallback to localhost
            web_urls = ["http://django_web:8080/", "http://localhost:8080/"]
            web_ok = False
            for url in web_urls:
                try:
                    res = await client.get(url)
                    if res.status_code in [200, 301, 302, 404]:
                        web_ok = True
                        break
                except Exception:
                    continue
            web_status = "ok" if web_ok else "unavailable"
    except Exception:
        web_status = "unavailable"

    # High-precision UTC ISO-8601 timestamp with millisecond precision: YYYY-MM-DDTHH:mm:ss.sssZ
    now_utc = datetime.now(timezone.utc)
    timestamp_str = now_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    is_overall_ok = (backend_status == "ok" and db_status == "ok" and cache_status == "ok")

    return {
        "status": "ok" if is_overall_ok else "degraded",
        "backend": backend_status,
        "database": db_status,
        "web": web_status,
        "cache-server": cache_status,
        "timestamp": timestamp_str
    }

# ----------------------------------------------------------------------------
# 1. LANDING LAYER INGESTION (High-Throughput Asynchronous Endpoint)
# ----------------------------------------------------------------------------

@app.post(f"{settings.API_V1_STR}/ingest/landing", tags=["1. Landing Layer"])
async def ingest_to_landing(request: LandingIngestRequest):
    """
    High-speed endpoint that stages raw payloads into the Landing layer without 
    blocking on complex 3NF transformations or relational constraints.
    """
    query = """
        INSERT INTO landing_books_ingest (raw_payload, source_channel)
        VALUES ($1::jsonb, $2)
        RETURNING ingest_id, received_at;
    """
    try:
        record = await db.fetch_one(query, json.dumps(request.payload), request.source_channel)
        return {
            "status": "queued",
            "ingest_id": str(record["ingest_id"]),
            "received_at": record["received_at"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Landing ingestion failed: {str(e)}")

# ----------------------------------------------------------------------------
# 2. SILVER LAYER (Catalog & Inventory Operations with Redis Caching)
# ----------------------------------------------------------------------------

@app.get(f"{settings.API_V1_STR}/books", tags=["2. Silver Layer (Catalog)"])
async def list_books():
    """
    Get full book catalog. Optimized with Redis sub-millisecond caching.
    """
    cache_key = "catalog:books:all"
    cached_books = await cache.get(cache_key)
    if cached_books is not None:
        return {"source": "cache", "data": cached_books}

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
        ORDER BY b.book_id DESC;
    """
    books = await db.fetch_all(query)
    await cache.set(cache_key, books, ttl=60)
    return {"source": "database", "data": books}

@app.post(f"{settings.API_V1_STR}/books", tags=["2. Silver Layer (Catalog)"])
async def create_book(book: BookCreateRequest):
    """
    Create a new book in Silver 3NF tables with automatic author/category resolution 
    and immediate Redis cache invalidation.
    """
    try:
        # Resolve Author ID
        author = await db.fetch_one("SELECT author_id FROM authors WHERE name = $1", book.author)
        if not author:
            author = await db.fetch_one("INSERT INTO authors (name) VALUES ($1) RETURNING author_id", book.author)
        author_id = author["author_id"]

        # Resolve Category ID
        category = await db.fetch_one("SELECT category_id FROM categories WHERE name = $1", book.category)
        if not category:
            category = await db.fetch_one("INSERT INTO categories (name) VALUES ($1) RETURNING category_id", book.category)
        category_id = category["category_id"]

        # Resolve Publisher ID
        publisher = await db.fetch_one("SELECT publisher_id FROM publishers WHERE name = $1", book.publisher)
        if not publisher:
            publisher = await db.fetch_one("INSERT INTO publishers (name) VALUES ($1) RETURNING publisher_id", book.publisher)
        publisher_id = publisher["publisher_id"]

        # Insert Book
        insert_query = """
            INSERT INTO books (title, author_id, category_id, publisher_id, price, total_copies, available_copies, isbn)
            VALUES ($1, $2, $3, $4, $5, $6, $6, $7)
            RETURNING book_id, title;
        """
        new_book = await db.fetch_one(
            insert_query,
            book.title, author_id, category_id, publisher_id, book.price, book.total_copies, book.isbn
        )

        # Invalidate catalog cache
        await cache.invalidate("catalog:books:*")
        return {"status": "success", "message": "Book created successfully", "book": new_book}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Book creation failed: {str(e)}")

@app.delete(f"{settings.API_V1_STR}/books/{{book_id}}", tags=["2. Silver Layer (Catalog)"])
async def delete_book(book_id: int):
    """Delete a book and invalidate cache."""
    try:
        res = await db.execute("DELETE FROM books WHERE book_id = $1", book_id)
        await cache.invalidate("catalog:books:*")
        return {"status": "success", "message": f"Book {book_id} deleted."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")

# ----------------------------------------------------------------------------
# 3. ATOMIC LOAN OPERATIONS (sp_issue_book & sp_return_book)
# ----------------------------------------------------------------------------

@app.post(f"{settings.API_V1_STR}/loans/issue", tags=["3. Transactions"])
async def issue_book(loan: LoanIssueRequest):
    """
    Executes atomic stored procedure `sp_issue_book` with row-level locking 
    to guarantee high-concurrency consistency (~1000 req/sec safety).
    """
    query = "SELECT * FROM sp_issue_book($1, $2, $3, $4);"
    try:
        result = await db.fetch_one(query, loan.student_id, loan.borrower_name, loan.book_title, loan.loan_days)
        if not result or not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"] if result else "Loan issue failed")
        
        await cache.invalidate("catalog:books:*")
        await cache.invalidate("loans:overdue:*")
        return {
            "status": "success",
            "message": result["message"],
            "record_id": result["record_id"],
            "due_date": result["due_date"]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Issue transaction failed: {str(e)}")

@app.post(f"{settings.API_V1_STR}/loans/return", tags=["3. Transactions"])
async def return_book(payload: LoanReturnRequest):
    """
    Executes atomic stored procedure `sp_return_book` to update inventory stock, 
    mark loans as returned, and calculate overdue fines.
    """
    query = "SELECT * FROM sp_return_book($1);"
    try:
        result = await db.fetch_one(query, payload.record_id)
        if not result or not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"] if result else "Return failed")

        await cache.invalidate("catalog:books:*")
        await cache.invalidate("loans:overdue:*")
        return {
            "status": "success",
            "message": result["message"],
            "returned_at": result["returned_at"],
            "fine_amount": float(result["fine_amount"])
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Return transaction failed: {str(e)}")

@app.get(f"{settings.API_V1_STR}/loans/overdue", tags=["3. Transactions"])
async def list_overdue_loans():
    """Fetch active overdue loans from Gold layer view `vw_gold_overdue_fines`."""
    cache_key = "loans:overdue:all"
    cached = await cache.get(cache_key)
    if cached is not None:
        return {"source": "cache", "data": cached}

    query = "SELECT * FROM vw_gold_overdue_fines;"
    records = await db.fetch_all(query)
    await cache.set(cache_key, records, ttl=30)
    return {"source": "database", "data": records}

# ----------------------------------------------------------------------------
# 4. GOLD LAYER ANALYTICS & REPORTING
# ----------------------------------------------------------------------------

@app.get(f"{settings.API_V1_STR}/analytics/gold-summary", tags=["4. Gold Layer Analytics"])
async def get_gold_analytics():
    """Retrieve top-level KPI metrics computed for business intelligence."""
    kpi_query = "SELECT * FROM gold_daily_kpi_summary ORDER BY summary_date DESC LIMIT 1;"
    popularity_query = "SELECT * FROM vw_gold_author_popularity ORDER BY total_times_borrowed DESC LIMIT 5;"
    inventory_query = "SELECT stock_status, COUNT(*) AS count FROM vw_gold_inventory_status GROUP BY stock_status;"

    kpis = await db.fetch_one(kpi_query)
    popularity = await db.fetch_all(popularity_query)
    inventory = await db.fetch_all(inventory_query)

    return {
        "daily_kpis": kpis or {},
        "top_authors": popularity,
        "inventory_health": inventory
    }
