import json
import requests
import psutil
from django.shortcuts import render, redirect
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from backend.config import settings
from .pipeline_manager import pipeline_mgr, STAGE_DISPLAY_NAMES

FASTAPI_BASE_URL = f"http://localhost:8000{settings.API_V1_STR}"

def get_medallion_metrics():
    """Helper to collect live distinct row counts across all Medallion tiers."""
    metrics = {
        # Distinct Tier Row Totals
        "landing_rows": 0,
        "bronze_rows": 0,
        "silver_rows": 0,

        # Landing Site Detailed Breakdown
        "landing_books_total": 0,
        "landing_borrow_total": 0,
        "landing_unprocessed": 0,
        "landing_total": 0,  # Backward compatibility alias

        # Bronze Layer Detailed Breakdown
        "bronze_books": 0,
        "bronze_borrow_records": 0,
        "bronze_errors": 0,

        # Silver Layer Detailed Breakdown
        "silver_books": 0,
        "silver_borrowers": 0,
        "silver_borrow_records": 0,
        "silver_active_loans": 0,
        "silver_overdue_loans": 0,
        "silver_categories": 0,
        "silver_authors": 0,
        "silver_publishers": 0,
        "silver_fine_payments": 0,

        # Gold Layer KPIs
        "gold_kpi": {}
    }

    try:
        with connection.cursor() as cursor:
            # 1. Landing Site rows
            cursor.execute("SELECT COUNT(*) FROM landing_books_ingest;")
            lb_total = cursor.fetchone()[0]
            metrics["landing_books_total"] = lb_total

            cursor.execute("SELECT COUNT(*) FROM landing_borrow_ingest;")
            lbr_total = cursor.fetchone()[0]
            metrics["landing_borrow_total"] = lbr_total

            metrics["landing_rows"] = lb_total + lbr_total
            metrics["landing_total"] = lb_total + lbr_total

            cursor.execute("""
                SELECT 
                    (SELECT COUNT(*) FROM landing_books_ingest WHERE processed_flag = FALSE) +
                    (SELECT COUNT(*) FROM landing_borrow_ingest WHERE processed_flag = FALSE);
            """)
            metrics["landing_unprocessed"] = cursor.fetchone()[0]

            # 2. Bronze Layer rows
            cursor.execute("SELECT COUNT(*) FROM bronze_books;")
            bb_count = cursor.fetchone()[0]
            metrics["bronze_books"] = bb_count

            cursor.execute("SELECT COUNT(*) FROM bronze_borrow_records;")
            bbr_count = cursor.fetchone()[0]
            metrics["bronze_borrow_records"] = bbr_count

            cursor.execute("SELECT COUNT(*) FROM bronze_ingestion_errors;")
            be_count = cursor.fetchone()[0]
            metrics["bronze_errors"] = be_count

            metrics["bronze_rows"] = bb_count + bbr_count + be_count

            # 3. Silver Layer rows (Operational 3NF)
            cursor.execute("SELECT COUNT(*) FROM books;")
            s_books = cursor.fetchone()[0]
            metrics["silver_books"] = s_books

            cursor.execute("SELECT COUNT(*) FROM borrowers;")
            s_borrowers = cursor.fetchone()[0]
            metrics["silver_borrowers"] = s_borrowers

            cursor.execute("SELECT COUNT(*) FROM borrow_records;")
            s_records = cursor.fetchone()[0]
            metrics["silver_borrow_records"] = s_records

            cursor.execute("SELECT COUNT(*) FROM categories;")
            s_cats = cursor.fetchone()[0]
            metrics["silver_categories"] = s_cats

            cursor.execute("SELECT COUNT(*) FROM authors;")
            s_authors = cursor.fetchone()[0]
            metrics["silver_authors"] = s_authors

            cursor.execute("SELECT COUNT(*) FROM publishers;")
            s_pubs = cursor.fetchone()[0]
            metrics["silver_publishers"] = s_pubs

            cursor.execute("SELECT COUNT(*) FROM fine_payments;")
            s_fines = cursor.fetchone()[0]
            metrics["silver_fine_payments"] = s_fines

            metrics["silver_rows"] = (s_books + s_borrowers + s_records + 
                                     s_cats + s_authors + s_pubs + s_fines)

            cursor.execute("SELECT COUNT(*) FROM borrow_records WHERE status = 'BORROWED';")
            metrics["silver_active_loans"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM borrow_records WHERE status = 'OVERDUE';")
            metrics["silver_overdue_loans"] = cursor.fetchone()[0]

            # 4. Gold Layer KPI summary
            cursor.execute("""
                SELECT summary_date, total_books_in_catalog, total_copies_available, 
                       total_active_loans, total_overdue_loans, total_fines_accrued, total_fines_collected 
                FROM gold_daily_kpi_summary 
                ORDER BY summary_date DESC LIMIT 1;
            """)
            row = cursor.fetchone()
            if row:
                cols = [col[0] for col in cursor.description]
                metrics["gold_kpi"] = dict(zip(cols, row))
    except Exception:
        pass

    return metrics


def home(request):
    """Home Dashboard: Quick checkout & system metrics summary."""
    metrics = get_medallion_metrics()
    
    # Fetch list of available books for quick selection
    available_books = []
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT title, available_copies 
            FROM books 
            WHERE available_copies > 0 
            ORDER BY title ASC LIMIT 50;
        """)
        for row in cursor.fetchall():
            available_books.append({"title": row[0], "available_copies": row[1]})

    context = {
        "active_tab": "home",
        "metrics": metrics,
        "available_books": available_books
    }
    return render(request, 'render/library.html', context)


def add_student(request):
    """Issues a book to a student using atomic stored procedure sp_issue_book via DB or FastAPI."""
    if request.method == "POST":
        name = request.POST.get('name', '').strip()
        roll_no = request.POST.get('roll_no', '').strip()
        book_title = request.POST.get('book_title', '').strip()
        
        if not name or not roll_no or not book_title:  
            metrics = get_medallion_metrics()
            return render(request, "render/library.html", {
                "error": "All fields are required!",
                "active_tab": "home",
                "metrics": metrics
            })
        
        # Execute atomic stored procedure sp_issue_book
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT success, message FROM sp_issue_book(%s, %s, %s, %s);",
                [roll_no, name, book_title, 7]
            )
            row = cursor.fetchone()
            if row and not row[0]:
                metrics = get_medallion_metrics()
                return render(request, "render/library.html", {
                    "error": row[1],
                    "active_tab": "home",
                    "metrics": metrics
                })

        return redirect('home')
    return redirect('home')


def book_list(request):
    """Renders catalog with search, category filter, and customizable pagination."""
    search_query = request.GET.get('q', '').strip()
    page_size = request.GET.get('page_size', '12')
    try:
        page_size = int(page_size)
        if page_size not in [8, 12, 24, 48]:
            page_size = 12
    except ValueError:
        page_size = 12

    page_number = request.GET.get('page', 1)

    query = """
        SELECT 
            b.book_id AS id,
            b.isbn,
            b.title,
            a.name AS author,
            c.name AS category,
            p.name AS publisher,
            b.price,
            b.total_copies,
            b.available_copies
        FROM books b
        JOIN authors a ON b.author_id = a.author_id
        LEFT JOIN categories c ON b.category_id = c.category_id
        LEFT JOIN publishers p ON b.publisher_id = p.publisher_id
    """
    params = []
    if search_query:
        query += " WHERE LOWER(b.title) LIKE %s OR LOWER(a.name) LIKE %s OR LOWER(b.isbn) LIKE %s "
        q_wildcard = f"%{search_query.lower()}%"
        params.extend([q_wildcard, q_wildcard, q_wildcard])

    query += " ORDER BY b.book_id DESC;"

    books = []
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        columns = [col[0] for col in cursor.description]
        for row in cursor.fetchall():
            books.append(dict(zip(columns, row)))

    paginator = Paginator(books, page_size)
    try:
        page_obj = paginator.page(page_number)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    context = {
        "active_tab": "books",
        "page_obj": page_obj,
        "books": page_obj.object_list,
        "search_query": search_query,
        "page_size": page_size,
        "total_books": len(books)
    }
    return render(request, 'render/books.html', context)


def delete_book(request, book_id):
    if request.method == "POST":
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM books WHERE book_id = %s;", [book_id])
    return redirect('book_list')


def add_book(request):
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        author = request.POST.get('author', '').strip()
        price = request.POST.get('price', '').strip()
        category = request.POST.get('category', 'Computer Science').strip()
        publisher = request.POST.get('publisher', 'Default Publisher').strip()
        isbn = request.POST.get('isbn', '').strip() or None
        total_copies = int(request.POST.get('total_copies', 1))

        if not title or not author or not price:  
            return redirect('book_list')

        with connection.cursor() as cursor:
            # Resolve Author
            cursor.execute("SELECT author_id FROM authors WHERE LOWER(name) = LOWER(%s);", [author])
            row = cursor.fetchone()
            if not row:
                cursor.execute("INSERT INTO authors (name) VALUES (%s) RETURNING author_id;", [author])
                author_id = cursor.fetchone()[0]
            else:
                author_id = row[0]

            # Resolve Category
            cursor.execute("SELECT category_id FROM categories WHERE LOWER(name) = LOWER(%s);", [category])
            cat_row = cursor.fetchone()
            if not cat_row:
                cursor.execute("INSERT INTO categories (name) VALUES (%s) RETURNING category_id;", [category])
                cat_id = cursor.fetchone()[0]
            else:
                cat_id = cat_row[0]

            # Resolve Publisher
            cursor.execute("SELECT publisher_id FROM publishers WHERE LOWER(name) = LOWER(%s);", [publisher])
            pub_row = cursor.fetchone()
            if not pub_row:
                cursor.execute("INSERT INTO publishers (name) VALUES (%s) RETURNING publisher_id;", [publisher])
                pub_id = cursor.fetchone()[0]
            else:
                pub_id = pub_row[0]

            # Upsert book
            cursor.execute("""
                INSERT INTO books (title, author_id, category_id, publisher_id, price, total_copies, available_copies, isbn)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (isbn) DO UPDATE SET 
                    total_copies = books.total_copies + EXCLUDED.total_copies,
                    available_copies = books.available_copies + EXCLUDED.total_copies,
                    price = EXCLUDED.price;
            """, [title, author_id, cat_id, pub_id, price, total_copies, total_copies, isbn])

    return redirect('book_list')


# ============================================================================
# Admin Dashboard & Medallion Pipeline Controller Views
# ============================================================================

def admin_dashboard(request):
    """Renders the interactive Medallion Pipeline Control & Monitoring Dashboard."""
    metrics = get_medallion_metrics()
    pipeline_status = pipeline_mgr.get_status()

    context = {
        "active_tab": "admin",
        "metrics": metrics,
        "pipeline": pipeline_status,
    }
    return render(request, 'render/admin_dashboard.html', context)


def api_pipeline_status(request):
    """Returns live JSON metrics and pipeline process status for AJAX polling."""
    metrics = get_medallion_metrics()
    status = pipeline_mgr.get_status()
    return JsonResponse({
        "status": "success",
        "pipeline": status,
        "metrics": metrics,
    })


def health_check(request):
    """Health check endpoint returning system status and high-precision UTC timestamp."""
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc)
    timestamp_str = now_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    db_status = "ok"
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
    except Exception:
        db_status = "disconnected"

    return JsonResponse({
        "status": "ok" if db_status == "ok" else "degraded",
        "backend": "ok",
        "database": db_status,
        "web": "ok",
        "cache-server": "ok",
        "timestamp": timestamp_str
    })


@csrf_exempt
def api_pipeline_start(request):
    """Starts a specific Medallion ETL pipeline stage asynchronously."""
    if request.method == "POST":
        pipeline_type = "landing_to_bronze"
        if request.content_type == "application/json":
            try:
                body = json.loads(request.body)
                pipeline_type = body.get("pipeline_type", body.get("type", "landing_to_bronze"))
            except Exception:
                pass
        else:
            pipeline_type = request.POST.get("pipeline_type", request.POST.get("type", "landing_to_bronze"))

        success, message = pipeline_mgr.start_pipeline(pipeline_type=pipeline_type)
        status_code = 202 if success else 409
        return JsonResponse({
            "status": "accepted" if success else "error",
            "success": success,
            "message": message,
            "pipeline": pipeline_mgr.get_status(),
        }, status=status_code)
    return JsonResponse({"status": "error", "success": False, "message": "POST method required."}, status=405)


@csrf_exempt
def api_pipeline_stop(request):
    """Stops the running Medallion ETL pipeline safely."""
    if request.method == "POST":
        success, message = pipeline_mgr.stop()
        return JsonResponse({
            "success": success,
            "message": message,
            "pipeline": pipeline_mgr.get_status(),
        })
    return JsonResponse({"success": False, "message": "POST method required."}, status=405)


@csrf_exempt
def api_pipeline_run_once(request):
    """Triggers an immediate Landing-to-Bronze Medallion ETL cycle."""
    if request.method == "POST":
        pipeline_type = request.POST.get("pipeline_type", "landing_to_bronze")
        success, message = pipeline_mgr.start_pipeline(pipeline_type=pipeline_type)
        status_code = 202 if success else 409
        return JsonResponse({
            "status": "accepted" if success else "error",
            "success": success,
            "message": message,
            "pipeline": pipeline_mgr.get_status(),
        }, status=status_code)
    return JsonResponse({"status": "error", "success": False, "message": "POST method required."}, status=405)


def api_pipeline_history(request):
    """
    Returns the last 50 pipeline run records, merging DB history with any
    in-memory-only records for the current session.
    """
    from .models import PipelineRunHistory

    try:
        db_runs = list(
            PipelineRunHistory.objects.order_by("-started_at")[:50].values(
                "id",
                "mode",
                "started_at",
                "ended_at",
                "status",
                "rows_landing_to_bronze",
                "rows_bronze_to_silver",
                "gold_refreshed",
                "error_message",
            )
        )
        # Serialise datetimes and add display name
        for run in db_runs:
            run["id"] = run["id"]
            run["pipeline_type_display"] = STAGE_DISPLAY_NAMES.get(run["mode"], run["mode"])
            run["started_at"] = run["started_at"].isoformat() if run["started_at"] else None
            run["ended_at"] = run["ended_at"].isoformat() if run["ended_at"] else None
            # Compute duration
            if run["started_at"] and run["ended_at"]:
                from datetime import datetime as dt
                try:
                    s = dt.fromisoformat(run["started_at"])
                    e = dt.fromisoformat(run["ended_at"])
                    run["duration_seconds"] = int((e - s).total_seconds())
                except Exception:
                    run["duration_seconds"] = None
            else:
                run["duration_seconds"] = None

        return JsonResponse({"status": "success", "runs": db_runs})
    except Exception as exc:
        # Fallback to in-memory history if DB is unavailable
        return JsonResponse({
            "status": "success",
            "runs": pipeline_mgr.history,
            "warning": f"DB unavailable, showing in-memory history: {exc}",
        })


def api_resource_monitor(request):
    """
    Returns live system resource metrics for the Admin Resource Monitor tab.
    Uses psutil for OS-level stats.
    """
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/") if not __import__("sys").platform.startswith("win") \
               else psutil.disk_usage("C:\\")

        # Django DB connection pool info (psycopg2 based)
        try:
            from django.db import connections
            db_conn = connections["default"]
            # psycopg2 doesn't expose pool stats easily; report connection alive status
            db_pool_info = {"status": "connected", "backend": "psycopg2"}
        except Exception:
            db_pool_info = {"status": "unknown"}

        return JsonResponse({
            "status": "success",
            "cpu": {
                "percent": cpu_percent,
                "count": psutil.cpu_count(logical=True),
            },
            "memory": {
                "total_mb": round(mem.total / 1024 / 1024, 1),
                "used_mb": round(mem.used / 1024 / 1024, 1),
                "available_mb": round(mem.available / 1024 / 1024, 1),
                "percent": mem.percent,
            },
            "disk": {
                "total_gb": round(disk.total / 1024 / 1024 / 1024, 1),
                "used_gb": round(disk.used / 1024 / 1024 / 1024, 1),
                "free_gb": round(disk.free / 1024 / 1024 / 1024, 1),
                "percent": disk.percent,
            },
            "db_pool": db_pool_info,
            "pipeline": {
                "is_running": pipeline_mgr.is_running,
                "mode": pipeline_mgr.mode,
            },
        })
    except Exception as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=500)
