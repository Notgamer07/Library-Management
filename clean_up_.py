"""
Enterprise Medallion Cleanup Utility (clean_up_.py)

Deletes test records created during load and read tests across all Medallion tiers:
  1. Silver Database (3NF Relational OLTP Core):
     - fine_payments (foreign key references to borrow_records)
     - borrow_records (active and returned test loans)
     - book_views (view audit logs on test books)
     - books (catalog records matching test patterns)
     - borrowers (test student records like STU-X-*, Test*)
     - orphaned authors, categories, publishers created by test runs
  2. Bronze Database (Raw Ingestion Layer & Staging):
     - bronze_books_ingest (raw book payloads)
     - bronze_borrow_ingest (raw borrow payloads)
     - bronze_book_views_ingest (raw book view payloads)
     - bronze_ingestion_errors (dead-letter audit logs)
  3. Gold Database (Analytics Data Mart):
     - gold_book_views_daily
     - gold_book_views_monthly
  4. Redis In-Memory Cache:
     - Invalidate/flush catalog and loan cache keys

Usage:
  python clean_up_.py              # Interactive confirmation
  python clean_up_.py --dry-run    # Preview record counts without deleting
  python clean_up_.py --yes        # Execute cleanup non-interactively
"""

import os
import sys
import argparse
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor

# Automatically load .env file if present
ROOT_DIR = Path(__file__).resolve().parent
env_file = ROOT_DIR / '.env'
if env_file.exists():
    with open(env_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# Connection configurations
BRONZE_HOST = "localhost" if not os.path.exists("/.dockerenv") else os.getenv("BRONZE_DB_HOST", "db_bronze")
BRONZE_PORT = int(os.getenv("BRONZE_DB_HOST_PORT", "5433")) if not os.path.exists("/.dockerenv") else int(os.getenv("BRONZE_DB_PORT", "5432"))
BRONZE_DB = os.getenv("BRONZE_DB_NAME", "bronze_db")
BRONZE_USER = os.getenv("BRONZE_DB_USER", "postgres")
BRONZE_PASS = os.getenv("BRONZE_DB_PASSWORD", "pass123")

SILVER_HOST = "localhost" if not os.path.exists("/.dockerenv") else os.getenv("SILVER_DB_HOST", "db_silver")
SILVER_PORT = int(os.getenv("SILVER_DB_HOST_PORT", "5434")) if not os.path.exists("/.dockerenv") else int(os.getenv("SILVER_DB_PORT", "5432"))
SILVER_DB = os.getenv("SILVER_DB_NAME", os.getenv("POSTGRES_DB", "silver_db"))
SILVER_USER = os.getenv("SILVER_DB_USER", os.getenv("POSTGRES_USER", "postgres"))
SILVER_PASS = os.getenv("SILVER_DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", "pass123"))

GOLD_HOST = "localhost" if not os.path.exists("/.dockerenv") else os.getenv("GOLD_DB_HOST", "db_gold")
GOLD_PORT = int(os.getenv("GOLD_DB_HOST_PORT", "5435")) if not os.path.exists("/.dockerenv") else int(os.getenv("GOLD_DB_PORT", "5432"))
GOLD_DB = os.getenv("GOLD_DB_NAME", "gold_db")
GOLD_USER = os.getenv("GOLD_DB_USER", "postgres")
GOLD_PASS = os.getenv("GOLD_DB_PASSWORD", "pass123")

REDIS_HOST = "localhost" if not os.path.exists("/.dockerenv") else os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASS = os.getenv("REDIS_PASSWORD", "") or None

DEFAULT_TITLE_PATTERNS = [
    "Benchmark Book #%",
    "LoadTest Book #%",
    "Test%"
]

DEFAULT_STUDENT_PATTERNS = [
    "STU-X-%",
    "TEST%",
    "STU-TEST%"
]


def get_connection(host, port, dbname, user, password):
    """Establishes psycopg2 connection with timeout."""
    return psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password,
        connect_timeout=5
    )


def preview_and_cleanup(dry_run: bool = False, extra_title_patterns: list = None):
    title_patterns = list(DEFAULT_TITLE_PATTERNS)
    if extra_title_patterns:
        title_patterns.extend(extra_title_patterns)

    student_patterns = list(DEFAULT_STUDENT_PATTERNS)

    print("=" * 75)
    print("           MEDALLION TEST DATA CLEANUP UTILITY (clean_up_.py)")
    print("=" * 75)
    print(f"Mode               : {'DRY RUN (Preview Only)' if dry_run else 'ACTIVE PURGE'}")
    print(f"Book Title Filters : {title_patterns}")
    print(f"Student ID Filters : {student_patterns}")
    print("=" * 75)
    print()

    # ------------------------------------------------------------------------
    # 1. SILVER DATABASE
    # ------------------------------------------------------------------------
    print(f"[1/4] Connecting to Silver Database at {SILVER_HOST}:{SILVER_PORT}/{SILVER_DB}...")
    try:
        silver_conn = get_connection(SILVER_HOST, SILVER_PORT, SILVER_DB, SILVER_USER, SILVER_PASS)
        silver_conn.autocommit = False
        with silver_conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Construct title WHERE clause
            title_clauses = " OR ".join(["bk.title LIKE %s" for _ in title_patterns])
            book_title_clauses = " OR ".join(["title LIKE %s" for _ in title_patterns])
            student_clauses = " OR ".join(["bw.student_id LIKE %s" for _ in student_patterns])
            borrower_student_clauses = " OR ".join(["student_id LIKE %s" for _ in student_patterns])

            # Count matching books
            cur.execute(f"SELECT COUNT(*) AS c FROM books WHERE {book_title_clauses};", title_patterns)
            books_count = cur.fetchone()["c"]

            # Count matching borrow records
            cur.execute(
                f"""
                SELECT COUNT(*) AS c FROM borrow_records br
                LEFT JOIN books bk ON br.book_id = bk.book_id
                LEFT JOIN borrowers bw ON br.borrower_id = bw.borrower_id
                WHERE ({title_clauses}) OR ({student_clauses}) OR bw.name = 'Student X';
                """,
                title_patterns + student_patterns
            )
            borrow_count = cur.fetchone()["c"]

            # Count matching fine payments
            cur.execute(
                f"""
                SELECT COUNT(*) AS c FROM fine_payments fp
                JOIN borrow_records br ON fp.record_id = br.record_id
                LEFT JOIN books bk ON br.book_id = bk.book_id
                LEFT JOIN borrowers bw ON br.borrower_id = bw.borrower_id
                WHERE ({title_clauses}) OR ({student_clauses}) OR bw.name = 'Student X';
                """,
                title_patterns + student_patterns
            )
            fines_count = cur.fetchone()["c"]

            # Count matching book views
            cur.execute(
                f"""
                SELECT COUNT(*) AS c FROM book_views bv
                JOIN books bk ON bv.book_id = bk.book_id
                WHERE {title_clauses};
                """,
                title_patterns
            )
            views_count = cur.fetchone()["c"]

            # Count matching test borrowers
            cur.execute(
                f"SELECT COUNT(*) AS c FROM borrowers WHERE ({borrower_student_clauses}) OR name = 'Student X';",
                student_patterns
            )
            borrowers_count = cur.fetchone()["c"]

            print(f"  * Silver books to delete          : {books_count}")
            print(f"  * Silver borrow_records to delete : {borrow_count}")
            print(f"  * Silver fine_payments to delete  : {fines_count}")
            print(f"  * Silver book_views to delete     : {views_count}")
            print(f"  * Silver borrowers to delete      : {borrowers_count}")

            if not dry_run:
                # 1. Delete fine payments
                cur.execute(
                    f"""
                    DELETE FROM fine_payments WHERE record_id IN (
                        SELECT br.record_id FROM borrow_records br
                        LEFT JOIN books bk ON br.book_id = bk.book_id
                        LEFT JOIN borrowers bw ON br.borrower_id = bw.borrower_id
                        WHERE ({title_clauses}) OR ({student_clauses}) OR bw.name = 'Student X'
                    );
                    """,
                    title_patterns + student_patterns
                )

                # 2. Delete borrow records
                cur.execute(
                    f"""
                    DELETE FROM borrow_records WHERE record_id IN (
                        SELECT br.record_id FROM borrow_records br
                        LEFT JOIN books bk ON br.book_id = bk.book_id
                        LEFT JOIN borrowers bw ON br.borrower_id = bw.borrower_id
                        WHERE ({title_clauses}) OR ({student_clauses}) OR bw.name = 'Student X'
                    );
                    """,
                    title_patterns + student_patterns
                )

                # 3. Delete book views
                cur.execute(
                    f"""
                    DELETE FROM book_views WHERE book_id IN (
                        SELECT book_id FROM books WHERE {book_title_clauses}
                    );
                    """,
                    title_patterns
                )

                # 4. Delete books
                cur.execute(f"DELETE FROM books WHERE {book_title_clauses};", title_patterns)

                # 5. Delete borrowers with no remaining loans
                cur.execute(
                    f"""
                    DELETE FROM borrowers
                    WHERE (({borrower_student_clauses}) OR name = 'Student X')
                      AND borrower_id NOT IN (SELECT DISTINCT borrower_id FROM borrow_records);
                    """,
                    student_patterns
                )

                # 6. Clean up orphaned authors/categories/publishers created by test scripts
                cur.execute("""
                    DELETE FROM authors WHERE author_id NOT IN (SELECT DISTINCT author_id FROM books) AND (name LIKE 'Author Benchmark%%' OR name LIKE 'Author %%' OR name LIKE 'Test%%');
                    DELETE FROM categories WHERE category_id NOT IN (SELECT DISTINCT category_id FROM books) AND name LIKE 'Test%%';
                    DELETE FROM publishers WHERE publisher_id NOT IN (SELECT DISTINCT publisher_id FROM books) AND name LIKE 'Test%%';
                """)

                silver_conn.commit()
                print("  [SUCCESS] Silver database test records purged successfully.")
        silver_conn.close()
    except Exception as e:
        print(f"  [ERROR] Silver database cleanup failed: {e}")

    # ------------------------------------------------------------------------
    # 2. BRONZE DATABASE
    # ------------------------------------------------------------------------
    print(f"\n[2/4] Connecting to Bronze Database at {BRONZE_HOST}:{BRONZE_PORT}/{BRONZE_DB}...")
    try:
        bronze_conn = get_connection(BRONZE_HOST, BRONZE_PORT, BRONZE_DB, BRONZE_USER, BRONZE_PASS)
        bronze_conn.autocommit = False
        with bronze_conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Raw books ingest conditions
            b_title_clauses = " OR ".join(["raw_payload->>'title' LIKE %s" for _ in title_patterns])
            params_b_books = list(title_patterns) + ["LOAD_TEST%"]
            cur.execute(
                f"SELECT COUNT(*) AS c FROM bronze_books_ingest WHERE ({b_title_clauses}) OR source_channel LIKE %s;",
                params_b_books
            )
            b_books_count = cur.fetchone()["c"]

            # Raw borrow ingest conditions
            b_borrow_title_clauses = " OR ".join(["raw_payload->>'book_title' LIKE %s" for _ in title_patterns])
            b_borrow_stu_clauses = " OR ".join(["raw_payload->>'student_id' LIKE %s" for _ in student_patterns])
            params_b_borrow = list(title_patterns) + list(student_patterns) + ["LOAD_TEST%", "API_BORROW_INGEST"]
            cur.execute(
                f"""
                SELECT COUNT(*) AS c FROM bronze_borrow_ingest
                WHERE ({b_borrow_title_clauses}) OR ({b_borrow_stu_clauses})
                   OR raw_payload->>'borrower_name' = 'Student X'
                   OR source_channel LIKE %s
                   OR source_channel = %s;
                """,
                params_b_borrow
            )
            b_borrow_count = cur.fetchone()["c"]

            # Errors & Views
            cur.execute("SELECT COUNT(*) AS c FROM bronze_book_views_ingest WHERE source_channel LIKE %s OR raw_payload->>'user_identifier' LIKE %s;", ["LOAD_TEST%", "TEST%"])
            b_views_count = cur.fetchone()["c"]

            cur.execute("SELECT COUNT(*) AS c FROM bronze_ingestion_errors WHERE raw_data::text LIKE %s OR raw_data::text LIKE %s;", ["%LoadTest%", "%Benchmark Book%"])
            b_errors_count = cur.fetchone()["c"]

            print(f"  * Bronze bronze_books_ingest to delete  : {b_books_count}")
            print(f"  * Bronze bronze_borrow_ingest to delete : {b_borrow_count}")
            print(f"  * Bronze bronze_book_views to delete    : {b_views_count}")
            print(f"  * Bronze ingestion errors to delete     : {b_errors_count}")

            if not dry_run:
                cur.execute(
                    f"DELETE FROM bronze_books_ingest WHERE ({b_title_clauses}) OR source_channel LIKE %s;",
                    params_b_books
                )
                cur.execute(
                    f"""
                    DELETE FROM bronze_borrow_ingest
                    WHERE ({b_borrow_title_clauses}) OR ({b_borrow_stu_clauses})
                       OR raw_payload->>'borrower_name' = 'Student X'
                       OR source_channel LIKE %s
                       OR source_channel = %s;
                    """,
                    params_b_borrow
                )
                cur.execute("DELETE FROM bronze_book_views_ingest WHERE source_channel LIKE %s OR raw_payload->>'user_identifier' LIKE %s;", ["LOAD_TEST%", "TEST%"])
                cur.execute("DELETE FROM bronze_ingestion_errors WHERE raw_data::text LIKE %s OR raw_data::text LIKE %s;", ["%LoadTest%", "%Benchmark Book%"])

                bronze_conn.commit()
                print("  [SUCCESS] Bronze database test staging records purged successfully.")
        bronze_conn.close()
    except Exception as e:
        print(f"  [ERROR] Bronze database cleanup failed: {e}")

    # ------------------------------------------------------------------------
    # 3. GOLD DATABASE
    # ------------------------------------------------------------------------
    print(f"\n[3/4] Connecting to Gold Database at {GOLD_HOST}:{GOLD_PORT}/{GOLD_DB}...")
    try:
        gold_conn = get_connection(GOLD_HOST, GOLD_PORT, GOLD_DB, GOLD_USER, GOLD_PASS)
        gold_conn.autocommit = False
        with gold_conn.cursor(cursor_factory=RealDictCursor) as cur:
            g_title_clauses = " OR ".join(["book_title LIKE %s" for _ in title_patterns])
            cur.execute(f"SELECT COUNT(*) AS c FROM gold_book_views_daily WHERE {g_title_clauses};", title_patterns)
            g_daily_count = cur.fetchone()["c"]

            cur.execute(f"SELECT COUNT(*) AS c FROM gold_book_views_monthly WHERE {g_title_clauses};", title_patterns)
            g_monthly_count = cur.fetchone()["c"]

            print(f"  * Gold daily book views to delete       : {g_daily_count}")
            print(f"  * Gold monthly book views to delete     : {g_monthly_count}")

            if not dry_run:
                cur.execute(f"DELETE FROM gold_book_views_daily WHERE {g_title_clauses};", title_patterns)
                cur.execute(f"DELETE FROM gold_book_views_monthly WHERE {g_title_clauses};", title_patterns)
                gold_conn.commit()
                print("  [SUCCESS] Gold database test aggregations purged successfully.")
        gold_conn.close()
    except Exception as e:
        print(f"  [ERROR] Gold database cleanup failed: {e}")

    # ------------------------------------------------------------------------
    # 4. REDIS IN-MEMORY CACHE
    # ------------------------------------------------------------------------
    print(f"\n[4/4] Connecting to Redis Cache at {REDIS_HOST}:{REDIS_PORT}...")
    try:
        import redis
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASS, decode_responses=True, socket_timeout=3)
        r.ping()

        keys_to_clear = []
        for pattern in ["catalog:books:*", "loans:overdue:*", "catalog:books:count"]:
            keys_to_clear.extend(r.keys(pattern))

        print(f"  * Redis cache keys found matching patterns : {len(keys_to_clear)}")
        if not dry_run and keys_to_clear:
            r.delete(*keys_to_clear)
            print(f"  [SUCCESS] Evicted {len(keys_to_clear)} cache keys from Redis.")
        elif dry_run:
            print("  [INFO] Dry run - skipped Redis key eviction.")
    except Exception as e:
        print(f"  [NOTE] Redis cache flush skipped: {e}")

    print("\n" + "=" * 75)
    if dry_run:
        print("DRY RUN COMPLETE: No data was modified. Run without --dry-run to purge.")
    else:
        print("CLEANUP COMPLETE: All test artifacts successfully removed.")
    print("=" * 75)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Purge all test/benchmark records from Bronze, Silver, Gold DBs and Redis."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview how many records would be deleted without actually deleting them."
    )
    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip interactive confirmation prompt and execute immediately."
    )
    parser.add_argument(
        "--pattern",
        action="append",
        dest="extra_patterns",
        help="Additional book title pattern(s) to match (e.g. --pattern 'CustomTest%')"
    )

    args = parser.parse_args()

    if not args.dry_run and not args.yes:
        print("WARNING: This will permanently delete test books, borrow records, and raw ingest rows.")
        confirm = input("Are you sure you want to proceed with cleanup? [y/N]: ").strip().lower()
        if confirm not in ["y", "yes"]:
            print("Cleanup cancelled.")
            sys.exit(0)

    preview_and_cleanup(dry_run=args.dry_run, extra_title_patterns=args.extra_patterns)
