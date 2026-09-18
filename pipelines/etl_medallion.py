import asyncio
import json
import logging
import argparse
import sys
import os
import asyncpg

# Add parent directory to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [Medallion-ETL] %(message)s"
)
logger = logging.getLogger("pipelines.etl_medallion")


class MedallionPipelineWorker:
    def __init__(self):
        self.pool = None

    async def connect(self):
        """Connect using read/write or dedicated pipeline worker credentials."""
        self.pool = await asyncpg.create_pool(
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            database=settings.POSTGRES_DB,
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            min_size=1,
            max_size=5
        )
        logger.info("Connected to PostgreSQL for Medallion ETL Pipeline execution.")

        # Ensure required unique constraint indexes exist for idempotent upserts without holding table locks
        async with self.pool.acquire() as conn:
            existing = await conn.fetch("""
                SELECT indexname FROM pg_indexes 
                WHERE indexname IN ('idx_bronze_books_ingest_id', 'idx_bronze_borrow_ingest_id');
            """)
            existing_names = {r["indexname"] for r in existing}
            if "idx_bronze_books_ingest_id" not in existing_names:
                await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_bronze_books_ingest_id ON bronze_books(ingest_id);")
            if "idx_bronze_borrow_ingest_id" not in existing_names:
                await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_bronze_borrow_ingest_id ON bronze_borrow_records(ingest_id);")

    async def disconnect(self):
        if self.pool:
            await self.pool.close()
            logger.info("Pipeline connection pool closed.")

    async def process_landing_to_bronze(self) -> int:
        """
        Stage 1: Extract unprocessed Landing records, perform hygiene & validation checks,
        and load clean rows into Bronze. Log invalid payloads to bronze_ingestion_errors.

        ACID guarantee: the entire batch runs inside a single explicit transaction.
        If the process is cancelled or an unrecoverable error occurs, the transaction
        rolls back — landing rows stay processed_flag=FALSE, no partial Bronze writes.

        Returns the count of successfully promoted records.
        """
        logger.info("Starting Stage 1: Landing -> Bronze Transformation...")
        promoted_count = 0
        error_count = 0

        async with self.pool.acquire() as conn:
            # Fetch candidates BEFORE opening the write transaction to avoid
            # long-held locks during the Python-side validation loop.
            records = await conn.fetch(
                "SELECT ingest_id, raw_payload FROM landing_books_ingest "
                "WHERE processed_flag = FALSE LIMIT 500;"
            )

            if not records:
                logger.info("Stage 1: No unprocessed Landing records found.")
                return 0

            # --- ACID Transaction boundary ---
            async with conn.transaction():
                for rec in records:
                    ingest_id = rec["ingest_id"]
                    raw_payload = rec["raw_payload"]

                    try:
                        async with conn.transaction():
                            # Raw payload can be string or dict (asyncpg jsonb returns dict)
                            data = (
                                json.loads(raw_payload)
                                if isinstance(raw_payload, str)
                                else raw_payload
                            )

                            # Data Hygiene & Validation
                            title = data.get("title", "").strip() if data.get("title") else None
                            author_name = data.get("author", "Unknown").strip()
                            category_name = data.get("category", "General").strip()
                            publisher_name = data.get("publisher", "Unknown Publisher").strip()
                            price = float(data.get("price", 0.00))
                            total_copies = int(data.get("total_copies", 1))
                            isbn = data.get("isbn", None)

                            if not title or price < 0 or total_copies < 0:
                                raise ValueError(
                                    f"Hygiene check failed: title={title!r}, "
                                    f"price={price}, copies={total_copies}"
                                )

                            # Write clean row to Bronze
                            await conn.execute(
                                """
                                INSERT INTO bronze_books
                                    (ingest_id, title, author_name, category_name,
                                     publisher_name, isbn, price, total_copies, is_valid)
                                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, TRUE)
                                ON CONFLICT (ingest_id) DO NOTHING;
                                """,
                                ingest_id, title, author_name, category_name,
                                publisher_name, isbn, price, total_copies,
                            )
                            promoted_count += 1

                    except Exception as val_err:
                        error_count += 1
                        logger.warning(f"Ingestion error on ingest_id {ingest_id}: {val_err}")
                        try:
                            await conn.execute(
                                """
                                INSERT INTO bronze_ingestion_errors
                                    (source_layer, raw_data, error_message)
                                VALUES ('LANDING', $1::jsonb, $2);
                                """,
                                (
                                    json.dumps(raw_payload)
                                    if isinstance(raw_payload, dict)
                                    else json.dumps({"raw": str(raw_payload)})
                                ),
                                str(val_err),
                            )
                        except Exception as log_err:
                            logger.error(f"Failed to record ingestion error: {log_err}")

                    # Mark Landing item as processed inside the same transaction
                    await conn.execute(
                        "UPDATE landing_books_ingest SET processed_flag = TRUE "
                        "WHERE ingest_id = $1;",
                        ingest_id,
                    )
            # --- Transaction committed here ---

        logger.info(
            f"Stage 1 Complete: {promoted_count} items promoted to Bronze, "
            f"{error_count} error items logged."
        )
        # Emit machine-readable stats line for pipeline_manager to parse
        print(f"STATS:landing_to_bronze:{promoted_count}", flush=True)
        return promoted_count

    async def process_bronze_to_silver(self) -> int:
        """
        Stage 2: Promote valid Bronze records into Silver 3NF tables with entity resolution.

        ACID guarantee: wrapped in a single transaction. A mid-run cancel rolls back
        all Silver inserts for this batch — no partial entity resolution state.

        Returns the count of successfully promoted records.
        """
        logger.info("Starting Stage 2: Bronze -> Silver 3NF Transformation...")
        promoted_count = 0

        async with self.pool.acquire() as conn:
            records = await conn.fetch(
                """
                SELECT bronze_id, title, author_name, category_name,
                       publisher_name, isbn, price, total_copies
                FROM bronze_books
                WHERE is_valid = TRUE
                  AND bronze_id NOT IN (
                      SELECT DISTINCT b.bronze_id
                      FROM bronze_books b
                      JOIN books bk ON bk.title = b.title AND bk.price = b.price
                      WHERE b.bronze_id IS NOT NULL
                  )
                LIMIT 500;
                """
            )

            if not records:
                logger.info("Stage 2: No eligible Bronze records to promote.")
                return 0

            # --- ACID Transaction boundary ---
            async with conn.transaction():
                for rec in records:
                    try:
                        async with conn.transaction():
                            # 1. Resolve Author (INSERT OR SELECT)
                            author = await conn.fetchrow(
                                "SELECT author_id FROM authors WHERE LOWER(name) = LOWER($1);",
                                rec["author_name"],
                            )
                            if not author:
                                author = await conn.fetchrow(
                                    "INSERT INTO authors (name) VALUES ($1) RETURNING author_id;",
                                    rec["author_name"],
                                )
                            author_id = author["author_id"]

                            # 2. Resolve Category
                            category = await conn.fetchrow(
                                "SELECT category_id FROM categories WHERE LOWER(name) = LOWER($1);",
                                rec["category_name"],
                            )
                            if not category:
                                category = await conn.fetchrow(
                                    "INSERT INTO categories (name) VALUES ($1) RETURNING category_id;",
                                    rec["category_name"],
                                )
                            category_id = category["category_id"]

                            # 3. Resolve Publisher
                            publisher = await conn.fetchrow(
                                "SELECT publisher_id FROM publishers WHERE LOWER(name) = LOWER($1);",
                                rec["publisher_name"],
                            )
                            if not publisher:
                                publisher = await conn.fetchrow(
                                    "INSERT INTO publishers (name) VALUES ($1) RETURNING publisher_id;",
                                    rec["publisher_name"],
                                )
                            publisher_id = publisher["publisher_id"]

                            # 4. Upsert into Silver books
                            await conn.execute(
                                """
                                INSERT INTO books
                                    (title, author_id, category_id, publisher_id,
                                     price, total_copies, available_copies, isbn)
                                VALUES ($1, $2, $3, $4, $5, $6, $6, $7)
                                ON CONFLICT (isbn) DO UPDATE SET
                                    total_copies = books.total_copies + EXCLUDED.total_copies,
                                    available_copies = books.available_copies + EXCLUDED.total_copies;
                                """,
                                rec["title"], author_id, category_id, publisher_id,
                                rec["price"], rec["total_copies"], rec["isbn"],
                            )
                            promoted_count += 1
                    except Exception as err:
                        logger.warning(f"Error promoting bronze record {rec.get('bronze_id')}: {err}")
            # --- Transaction committed here ---

        logger.info(
            f"Stage 2 Complete: {promoted_count} valid Bronze items inserted into Silver 3NF."
        )
        print(f"STATS:bronze_to_silver:{promoted_count}", flush=True)
        return promoted_count

    async def process_silver_to_gold(self) -> bool:
        """
        Stage 3: Refresh Gold layer analytical summary views and daily KPI tables.
        The stored procedure itself is transactional on the Postgres side.

        Returns True if the refresh succeeded.
        """
        logger.info("Starting Stage 3: Refreshing Gold Layer Analytics & KPIs...")
        async with self.pool.acquire() as conn:
            await conn.execute("SELECT sp_refresh_gold_analytics();")
        logger.info("Stage 3 Complete: Gold analytics summary successfully refreshed.")
        print("STATS:gold_refreshed:1", flush=True)
        return True

    async def run_pipeline_once(self):
        """Execute full Medallion pipeline (Landing -> Bronze -> Silver -> Gold).
        
        Each stage runs in its own ACID transaction. If the process receives
        SIGTERM (e.g. pipeline_manager calls stop()), asyncio raises CancelledError
        which propagates out of the transaction context manager, triggering a
        ROLLBACK automatically via asyncpg.
        """
        logger.info("=================== Executing Medallion Pipeline Cycle ===================")
        rows_l2b = await self.process_landing_to_bronze()
        rows_b2s = await self.process_bronze_to_silver()
        await self.process_silver_to_gold()
        logger.info(
            f"=================== Medallion Pipeline Cycle Finished "
            f"[L→B: {rows_l2b}, B→S: {rows_b2s}] ===================\n"
        )

    async def start_scheduled_loop(self, interval_seconds: int = 90):
        """Run the pipeline on a scheduled loop every N seconds (default 90s)."""
        logger.info(
            f"Starting scheduled Medallion ETL daemon (Interval: {interval_seconds}s)..."
        )
        await self.connect()
        try:
            while True:
                await self.run_pipeline_once()
                await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("Scheduled Medallion ETL loop cancelled — transactions rolled back.")
        finally:
            await self.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Medallion Data Pipeline Worker")
    parser.add_argument(
        "--stage",
        type=str,
        choices=["landing_to_bronze", "bronze_to_silver", "silver_to_gold", "all"],
        default=None,
        help="Execute a specific stage of the Medallion pipeline (landing_to_bronze, bronze_to_silver, silver_to_gold, all).",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Run a single pipeline cycle and exit.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=90,
        help="Interval in seconds for scheduled ETL daemon (default 90s = 1.5 mins).",
    )
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    worker = MedallionPipelineWorker()

    async def run_stage_wrapper(stage: str):
        await worker.connect()
        try:
            if stage == "landing_to_bronze":
                await worker.process_landing_to_bronze()
            elif stage == "bronze_to_silver":
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
