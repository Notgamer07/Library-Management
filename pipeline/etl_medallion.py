import asyncio
import json
import logging
import argparse
import sys
import os
import asyncpg
from datetime import datetime, timezone

# Add parent directory to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [Medallion-ETL] %(message)s"
)
logger = logging.getLogger("pipeline.etl_medallion")


class MedallionPipelineWorker:
    def __init__(self, batch_size: int = None):
        self.bronze_pool = None
        self.silver_pool = None
        self.gold_pool = None
        self.batch_size = batch_size or settings.PIPELINE_BATCH_SIZE

    async def connect(self):
        """Connect to Bronze, Silver, and Gold database instances."""
        # 1. Bronze Database (Raw Ingestion Layer & Error Audit)
        self.bronze_pool = await asyncpg.create_pool(
            user=settings.BRONZE_DB_USER,
            password=settings.BRONZE_DB_PASSWORD,
            database=settings.BRONZE_DB_NAME,
            host=settings.BRONZE_DB_HOST,
            port=settings.BRONZE_DB_PORT,
            min_size=1,
            max_size=5
        )
        logger.info(f"Connected to Bronze Database at {settings.BRONZE_DB_HOST}:{settings.BRONZE_DB_PORT}/{settings.BRONZE_DB_NAME}")

        # 2. Silver Database (3NF Relational OLTP Core)
        self.silver_pool = await asyncpg.create_pool(
            user=settings.SILVER_DB_USER,
            password=settings.SILVER_DB_PASSWORD,
            database=settings.SILVER_DB_NAME,
            host=settings.SILVER_DB_HOST,
            port=settings.SILVER_DB_PORT,
            min_size=1,
            max_size=5
        )
        logger.info(f"Connected to Silver Database at {settings.SILVER_DB_HOST}:{settings.SILVER_DB_PORT}/{settings.SILVER_DB_NAME}")

        # 3. Gold Database (Dedicated Analytics & Reporting)
        self.gold_pool = await asyncpg.create_pool(
            user=settings.GOLD_DB_USER,
            password=settings.GOLD_DB_PASSWORD,
            database=settings.GOLD_DB_NAME,
            host=settings.GOLD_DB_HOST,
            port=settings.GOLD_DB_PORT,
            min_size=1,
            max_size=5
        )
        logger.info(f"Connected to Gold Database at {settings.GOLD_DB_HOST}:{settings.GOLD_DB_PORT}/{settings.GOLD_DB_NAME}")

    async def disconnect(self):
        """Close all connection pools gracefully."""
        if self.bronze_pool:
            await self.bronze_pool.close()
        if self.silver_pool:
            await self.silver_pool.close()
        if self.gold_pool:
            await self.gold_pool.close()
        logger.info("All pipeline database connection pools closed.")

    async def process_bronze_to_silver(self) -> int:
        """
        Stage 1: Extract unprocessed raw records from Bronze DB,
        perform in-memory validation checks, and ingest clean rows into Silver DB
        inside an atomic ACID transaction.
        Invalid rows are diverted to bronze_ingestion_errors (Dead Letter Queue).
        """
        logger.info("Bronze-Silver Pipeline started")
        total_fetched = 0
        inserted_clean_count = 0
        error_count = 0

        async with self.bronze_pool.acquire() as bronze_conn, self.silver_pool.acquire() as silver_conn:
            # 1. Fetch raw books ingest records
            book_records = await bronze_conn.fetch(
                "SELECT ingest_id, raw_payload FROM bronze_books_ingest "
                "WHERE processed_flag = FALSE ORDER BY received_at ASC LIMIT $1;",
                self.batch_size
            )

            # 2. Fetch raw borrow/loan ingest records
            borrow_records = await bronze_conn.fetch(
                "SELECT ingest_id, raw_payload FROM bronze_borrow_ingest "
                "WHERE processed_flag = FALSE ORDER BY received_at ASC LIMIT $1;",
                self.batch_size
            )

            # 3. Fetch raw book views ingest records
            view_records = await bronze_conn.fetch(
                "SELECT view_id, raw_payload FROM bronze_book_views_ingest "
                "WHERE processed_flag = FALSE ORDER BY received_at ASC LIMIT $1;",
                self.batch_size
            )

            total_fetched = len(book_records) + len(borrow_records) + len(view_records)
            logger.info(f"Fetched ({total_fetched}) unprocessed records")

            if total_fetched == 0:
                logger.info("Inserted (0) clean records in SilverDB successfully")
                print("STATS:bronze_to_silver:0", flush=True)
                return 0

            # --- A. Process Books Ingestion ---
            for rec in book_records:
                ingest_id = rec["ingest_id"]
                raw_payload = rec["raw_payload"]
                try:
                    data = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
                    title = data.get("title", "").strip() if data.get("title") else None
                    author_name = data.get("author", "Unknown").strip()
                    category_name = data.get("category", "General").strip()
                    publisher_name = data.get("publisher", "Unknown Publisher").strip()
                    price = float(data.get("price", 0.00))
                    total_copies = int(data.get("total_copies", 1))
                    isbn = data.get("isbn", None)

                    # Hygiene & Validation
                    if not title or price < 0 or total_copies < 0:
                        raise ValueError(f"Hygiene check failed: title={title!r}, price={price}, copies={total_copies}")

                    # ACID Ingestion into Silver DB
                    async with silver_conn.transaction():
                        # Resolve Author
                        author = await silver_conn.fetchrow(
                            "SELECT author_id FROM authors WHERE LOWER(name) = LOWER($1);",
                            author_name
                        )
                        if not author:
                            author = await silver_conn.fetchrow(
                                "INSERT INTO authors (name) VALUES ($1) RETURNING author_id;",
                                author_name
                            )
                        author_id = author["author_id"]

                        # Resolve Category
                        category = await silver_conn.fetchrow(
                            "SELECT category_id FROM categories WHERE LOWER(name) = LOWER($1);",
                            category_name
                        )
                        if not category:
                            category = await silver_conn.fetchrow(
                                "INSERT INTO categories (name) VALUES ($1) RETURNING category_id;",
                                category_name
                            )
                        category_id = category["category_id"]

                        # Resolve Publisher
                        publisher = await silver_conn.fetchrow(
                            "SELECT publisher_id FROM publishers WHERE LOWER(name) = LOWER($1);",
                            publisher_name
                        )
                        if not publisher:
                            publisher = await silver_conn.fetchrow(
                                "INSERT INTO publishers (name) VALUES ($1) RETURNING publisher_id;",
                                publisher_name
                            )
                        publisher_id = publisher["publisher_id"]

                        # Upsert Book
                        await silver_conn.execute(
                            """
                            INSERT INTO books (title, author_id, category_id, publisher_id, price, total_copies, available_copies, isbn)
                            VALUES ($1, $2, $3, $4, $5, $6, $6, $7)
                            ON CONFLICT (isbn) DO UPDATE SET
                                total_copies = books.total_copies + EXCLUDED.total_copies,
                                available_copies = books.available_copies + EXCLUDED.total_copies;
                            """,
                            title, author_id, category_id, publisher_id, price, total_copies, isbn
                        )

                    inserted_clean_count += 1
                except Exception as val_err:
                    error_count += 1
                    await bronze_conn.execute(
                        "INSERT INTO bronze_ingestion_errors (source_layer, source_stream, raw_data, error_message) VALUES ('BRONZE', 'BOOKS', $1::jsonb, $2);",
                        json.dumps(raw_payload) if isinstance(raw_payload, dict) else json.dumps({"raw": str(raw_payload)}),
                        str(val_err)
                    )

                # Mark processed in Bronze DB
                await bronze_conn.execute(
                    "UPDATE bronze_books_ingest SET processed_flag = TRUE WHERE ingest_id = $1;",
                    ingest_id
                )

            # --- B. Process Borrow Ingestion ---
            for rec in borrow_records:
                ingest_id = rec["ingest_id"]
                raw_payload = rec["raw_payload"]
                try:
                    data = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
                    action = data.get("action", "ISSUE")

                    if action == "ISSUE":
                        student_id = data.get("student_id", "").strip()
                        borrower_name = data.get("borrower_name", "").strip()
                        book_title = data.get("book_title", "").strip()
                        loan_days = int(data.get("loan_days", 7))

                        if not student_id or not borrower_name or not book_title:
                            raise ValueError(f"Missing required fields for loan issue: {data}")

                        # Execute atomic stored procedure sp_issue_book in Silver DB
                        async with silver_conn.transaction():
                            result = await silver_conn.fetchrow(
                                "SELECT * FROM sp_issue_book($1, $2, $3, $4);",
                                student_id, borrower_name, book_title, loan_days
                            )
                            if result and not result["success"]:
                                raise ValueError(f"sp_issue_book rejected: {result['message']}")

                        inserted_clean_count += 1

                    elif action == "RETURN":
                        record_id = int(data.get("record_id", 0))
                        if record_id <= 0:
                            raise ValueError(f"Invalid record_id for return: {record_id}")

                        # Execute atomic stored procedure sp_return_book in Silver DB
                        async with silver_conn.transaction():
                            result = await silver_conn.fetchrow(
                                "SELECT * FROM sp_return_book($1);",
                                record_id
                            )
                            if result and not result["success"]:
                                raise ValueError(f"sp_return_book rejected: {result['message']}")

                        inserted_clean_count += 1
                except Exception as b_err:
                    error_count += 1
                    await bronze_conn.execute(
                        "INSERT INTO bronze_ingestion_errors (source_layer, source_stream, raw_data, error_message) VALUES ('BRONZE', 'BORROW', $1::jsonb, $2);",
                        json.dumps(raw_payload) if isinstance(raw_payload, dict) else json.dumps({"raw": str(raw_payload)}),
                        str(b_err)
                    )

                # Mark processed in Bronze DB
                await bronze_conn.execute(
                    "UPDATE bronze_borrow_ingest SET processed_flag = TRUE WHERE ingest_id = $1;",
                    ingest_id
                )

            # --- C. Process Book Views Ingestion ---
            for rec in view_records:
                view_id = rec["view_id"]
                raw_payload = rec["raw_payload"]
                try:
                    data = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
                    book_id = int(data.get("book_id", 0))
                    user_identifier = str(data.get("user_identifier", "ANONYMOUS")).strip()

                    if book_id <= 0:
                        raise ValueError(f"Invalid book_id for view event: {book_id}")

                    # Ingest view into Silver DB
                    async with silver_conn.transaction():
                        await silver_conn.execute(
                            "INSERT INTO book_views (book_id, user_identifier) VALUES ($1, $2);",
                            book_id, user_identifier
                        )

                    inserted_clean_count += 1
                except Exception as v_err:
                    error_count += 1
                    await bronze_conn.execute(
                        "INSERT INTO bronze_ingestion_errors (source_layer, source_stream, raw_data, error_message) VALUES ('BRONZE', 'BOOK_VIEWS', $1::jsonb, $2);",
                        json.dumps(raw_payload) if isinstance(raw_payload, dict) else json.dumps({"raw": str(raw_payload)}),
                        str(v_err)
                    )

                # Mark processed in Bronze DB
                await bronze_conn.execute(
                    "UPDATE bronze_book_views_ingest SET processed_flag = TRUE WHERE view_id = $1;",
                    view_id
                )

        if error_count > 0:
            logger.warning(f"Logged ({error_count}) invalid records to Bronze Dead Letter Queue")

        logger.info(f"Inserted ({inserted_clean_count}) clean records in SilverDB successfully")
        print(f"STATS:bronze_to_silver:{inserted_clean_count}", flush=True)
        return inserted_clean_count

    async def process_silver_to_gold(self) -> bool:
        """
        Stage 2: Aggregate metrics from Silver DB and populate Gold DB data marts:
        1. Day-wise & Month-wise user book views.
        2. Day-wise & Month-wise book loans & returns.
        """
        logger.info("Silver-Gold Pipeline started")

        async with self.silver_pool.acquire() as silver_conn, self.gold_pool.acquire() as gold_conn:
            # 1. Day-wise Book Views Aggregation
            daily_views = await silver_conn.fetch("""
                SELECT 
                    DATE(bv.viewed_at) AS summary_date,
                    b.book_id,
                    b.title AS book_title,
                    c.name AS category_name,
                    COUNT(bv.view_id) AS total_views,
                    COUNT(DISTINCT bv.user_identifier) AS unique_users
                FROM book_views bv
                JOIN books b ON bv.book_id = b.book_id
                LEFT JOIN categories c ON b.category_id = c.category_id
                GROUP BY DATE(bv.viewed_at), b.book_id, b.title, c.name;
            """)

            for row in daily_views:
                await gold_conn.execute("""
                    INSERT INTO gold_book_views_daily (summary_date, book_id, book_title, category_name, total_views, unique_users, last_updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, CURRENT_TIMESTAMP)
                    ON CONFLICT (summary_date, book_id) DO UPDATE SET
                        total_views = EXCLUDED.total_views,
                        unique_users = EXCLUDED.unique_users,
                        last_updated_at = CURRENT_TIMESTAMP;
                """, row["summary_date"], row["book_id"], row["book_title"], row["category_name"], row["total_views"], row["unique_users"])

            # 2. Month-wise Book Views Aggregation
            monthly_views = await silver_conn.fetch("""
                SELECT 
                    EXTRACT(YEAR FROM bv.viewed_at)::INT AS summary_year,
                    EXTRACT(MONTH FROM bv.viewed_at)::INT AS summary_month,
                    b.book_id,
                    b.title AS book_title,
                    c.name AS category_name,
                    COUNT(bv.view_id) AS total_views,
                    COUNT(DISTINCT bv.user_identifier) AS unique_users
                FROM book_views bv
                JOIN books b ON bv.book_id = b.book_id
                LEFT JOIN categories c ON b.category_id = c.category_id
                GROUP BY EXTRACT(YEAR FROM bv.viewed_at), EXTRACT(MONTH FROM bv.viewed_at), b.book_id, b.title, c.name;
            """)

            for row in monthly_views:
                await gold_conn.execute("""
                    INSERT INTO gold_book_views_monthly (summary_year, summary_month, book_id, book_title, category_name, total_views, unique_users, last_updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, CURRENT_TIMESTAMP)
                    ON CONFLICT (summary_year, summary_month, book_id) DO UPDATE SET
                        total_views = EXCLUDED.total_views,
                        unique_users = EXCLUDED.unique_users,
                        last_updated_at = CURRENT_TIMESTAMP;
                """, row["summary_year"], row["summary_month"], row["book_id"], row["book_title"], row["category_name"], row["total_views"], row["unique_users"])

            # 3. Day-wise Loans & Returns Aggregation
            daily_loans_returns = await silver_conn.fetch("""
                SELECT 
                    d.summary_date,
                    COALESCE(l.loans_count, 0) AS total_loans,
                    COALESCE(r.returns_count, 0) AS total_returns,
                    COALESCE(o.overdue_count, 0) AS total_overdue,
                    COALESCE(f.fines_accrued, 0.00) AS total_fines_accrued,
                    COALESCE(p.fines_collected, 0.00) AS total_fines_collected
                FROM (
                    SELECT DISTINCT DATE(borrowed_at) AS summary_date FROM borrow_records
                    UNION
                    SELECT DISTINCT DATE(returned_at) AS summary_date FROM borrow_records WHERE returned_at IS NOT NULL
                ) d
                LEFT JOIN (
                    SELECT DATE(borrowed_at) AS dt, COUNT(*) AS loans_count FROM borrow_records GROUP BY DATE(borrowed_at)
                ) l ON d.summary_date = l.dt
                LEFT JOIN (
                    SELECT DATE(returned_at) AS dt, COUNT(*) AS returns_count FROM borrow_records WHERE returned_at IS NOT NULL GROUP BY DATE(returned_at)
                ) r ON d.summary_date = r.dt
                LEFT JOIN (
                    SELECT DATE(borrowed_at) AS dt, COUNT(*) AS overdue_count FROM borrow_records WHERE status = 'OVERDUE' GROUP BY DATE(borrowed_at)
                ) o ON d.summary_date = o.dt
                LEFT JOIN (
                    SELECT DATE(borrowed_at) AS dt, SUM(fine_amount) AS fines_accrued FROM borrow_records GROUP BY DATE(borrowed_at)
                ) f ON d.summary_date = f.dt
                LEFT JOIN (
                    SELECT DATE(paid_at) AS dt, SUM(amount) AS fines_collected FROM fine_payments GROUP BY DATE(paid_at)
                ) p ON d.summary_date = p.dt;
            """)

            for row in daily_loans_returns:
                await gold_conn.execute("""
                    INSERT INTO gold_loans_returns_daily (summary_date, total_loans, total_returns, total_overdue, total_fines_accrued, total_fines_collected, last_updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, CURRENT_TIMESTAMP)
                    ON CONFLICT (summary_date) DO UPDATE SET
                        total_loans = EXCLUDED.total_loans,
                        total_returns = EXCLUDED.total_returns,
                        total_overdue = EXCLUDED.total_overdue,
                        total_fines_accrued = EXCLUDED.total_fines_accrued,
                        total_fines_collected = EXCLUDED.total_fines_collected,
                        last_updated_at = CURRENT_TIMESTAMP;
                """, row["summary_date"], row["total_loans"], row["total_returns"], row["total_overdue"], row["total_fines_accrued"], row["total_fines_collected"])

            # 4. Month-wise Loans & Returns Aggregation
            monthly_loans_returns = await silver_conn.fetch("""
                SELECT 
                    m.summary_year,
                    m.summary_month,
                    COALESCE(l.loans_count, 0) AS total_loans,
                    COALESCE(r.returns_count, 0) AS total_returns,
                    COALESCE(o.overdue_count, 0) AS total_overdue,
                    COALESCE(f.fines_accrued, 0.00) AS total_fines_accrued,
                    COALESCE(p.fines_collected, 0.00) AS total_fines_collected
                FROM (
                    SELECT DISTINCT EXTRACT(YEAR FROM borrowed_at)::INT AS summary_year, EXTRACT(MONTH FROM borrowed_at)::INT AS summary_month FROM borrow_records
                    UNION
                    SELECT DISTINCT EXTRACT(YEAR FROM returned_at)::INT AS summary_year, EXTRACT(MONTH FROM returned_at)::INT AS summary_month FROM borrow_records WHERE returned_at IS NOT NULL
                ) m
                LEFT JOIN (
                    SELECT EXTRACT(YEAR FROM borrowed_at)::INT AS yr, EXTRACT(MONTH FROM borrowed_at)::INT AS mo, COUNT(*) AS loans_count FROM borrow_records GROUP BY yr, mo
                ) l ON m.summary_year = l.yr AND m.summary_month = l.mo
                LEFT JOIN (
                    SELECT EXTRACT(YEAR FROM returned_at)::INT AS yr, EXTRACT(MONTH FROM returned_at)::INT AS mo, COUNT(*) AS returns_count FROM borrow_records WHERE returned_at IS NOT NULL GROUP BY yr, mo
                ) r ON m.summary_year = r.yr AND m.summary_month = r.mo
                LEFT JOIN (
                    SELECT EXTRACT(YEAR FROM borrowed_at)::INT AS yr, EXTRACT(MONTH FROM borrowed_at)::INT AS mo, COUNT(*) AS overdue_count FROM borrow_records WHERE status = 'OVERDUE' GROUP BY yr, mo
                ) o ON m.summary_year = o.yr AND m.summary_month = o.mo
                LEFT JOIN (
                    SELECT EXTRACT(YEAR FROM borrowed_at)::INT AS yr, EXTRACT(MONTH FROM borrowed_at)::INT AS mo, SUM(fine_amount) AS fines_accrued FROM borrow_records GROUP BY yr, mo
                ) f ON m.summary_year = f.yr AND m.summary_month = f.mo
                LEFT JOIN (
                    SELECT EXTRACT(YEAR FROM paid_at)::INT AS yr, EXTRACT(MONTH FROM paid_at)::INT AS mo, SUM(amount) AS fines_collected FROM fine_payments GROUP BY yr, mo
                ) p ON m.summary_year = p.yr AND m.summary_month = p.mo;
            """)

            for row in monthly_loans_returns:
                await gold_conn.execute("""
                    INSERT INTO gold_loans_returns_monthly (summary_year, summary_month, total_loans, total_returns, total_overdue, total_fines_accrued, total_fines_collected, last_updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, CURRENT_TIMESTAMP)
                    ON CONFLICT (summary_year, summary_month) DO UPDATE SET
                        total_loans = EXCLUDED.total_loans,
                        total_returns = EXCLUDED.total_returns,
                        total_overdue = EXCLUDED.total_overdue,
                        total_fines_accrued = EXCLUDED.total_fines_accrued,
                        total_fines_collected = EXCLUDED.total_fines_collected,
                        last_updated_at = CURRENT_TIMESTAMP;
                """, row["summary_year"], row["summary_month"], row["total_loans"], row["total_returns"], row["total_overdue"], row["total_fines_accrued"], row["total_fines_collected"])

        logger.info("Aggregated day-wise and month-wise metrics into GoldDB successfully")
        logger.info("Silver-Gold Pipeline completed")
        print("STATS:gold_refreshed:1", flush=True)
        return True

    async def run_pipeline_once(self):
        """Execute full Medallion pipeline (Bronze -> Silver -> Gold)."""
        logger.info("=================== Executing Medallion Pipeline Cycle ===================")
        rows_b2s = await self.process_bronze_to_silver()
        await self.process_silver_to_gold()
        logger.info(
            f"=================== Medallion Pipeline Cycle Finished [Bronze->Silver: {rows_b2s}] ===================\n"
        )

    async def start_scheduled_loop(self, interval_seconds: int = 90):
        """Run the pipeline on a scheduled loop every N seconds (default 90s)."""
        logger.info(f"Starting scheduled Medallion ETL daemon (Interval: {interval_seconds}s, Batch: {self.batch_size})...")
        await self.connect()
        try:
            while True:
                await self.run_pipeline_once()
                await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("Scheduled Medallion ETL loop cancelled.")
        finally:
            await self.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Medallion Data Pipeline Worker")
    parser.add_argument(
        "--stage",
        type=str,
        choices=["bronze_to_silver", "silver_to_gold", "all", "landing_to_bronze"],
        default=None,
        help="Execute a specific stage of the Medallion pipeline (bronze_to_silver, silver_to_gold, all).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=settings.PIPELINE_BATCH_SIZE,
        help="Maximum records to process per batch (default: 10000).",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Run a single pipeline cycle and exit.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=settings.PIPELINE_INTERVAL_SECONDS,
        help="Interval in seconds for scheduled ETL daemon (default 90s).",
    )
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    worker = MedallionPipelineWorker(batch_size=args.batch_size)

    async def run_stage_wrapper(stage: str):
        await worker.connect()
        try:
            if stage in ["bronze_to_silver", "landing_to_bronze"]:
                await worker.process_bronze_to_silver()
            elif stage == "silver_to_gold":
                await worker.process_silver_to_gold()
            elif stage == "all":
                await worker.run_pipeline_once()
        finally:
            await worker.disconnect()

    if args.stage:
        try:
            asyncio.run(run_stage_wrapper(args.stage))
            sys.exit(0)
        except Exception as e:
            logger.exception(f"Medallion pipeline stage '{args.stage}' failed: {e}")
            sys.exit(1)
    elif args.run_once:
        try:
            asyncio.run(run_stage_wrapper("all"))
            sys.exit(0)
        except Exception as e:
            logger.exception(f"Pipeline run-once failed: {e}")
            sys.exit(1)
    else:
        try:
            asyncio.run(worker.start_scheduled_loop(interval_seconds=args.interval_seconds))
            sys.exit(0)
        except Exception as e:
            logger.exception(f"Pipeline daemon failed: {e}")
            sys.exit(1)
