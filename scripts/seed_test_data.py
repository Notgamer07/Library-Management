import asyncio
import json
import sys
import os
from datetime import datetime, timedelta, timezone

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg
from backend.config import settings

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

async def seed_data():
    silver_port = int(os.getenv("SILVER_DB_HOST_PORT", os.getenv("SILVER_DB_PORT", "5432")))
    bronze_port = int(os.getenv("BRONZE_DB_HOST_PORT", os.getenv("BRONZE_DB_PORT", "5433")))
    gold_port = int(os.getenv("GOLD_DB_HOST_PORT", os.getenv("GOLD_DB_PORT", "5435")))
    host = "localhost" if settings.SILVER_DB_HOST == "db_silver" else settings.SILVER_DB_HOST

    print(f"Connecting to Silver Database at {host}:{silver_port}/{settings.SILVER_DB_NAME}...")
    silver_conn = await asyncpg.connect(
        user=settings.SILVER_DB_USER,
        password=settings.SILVER_DB_PASSWORD,
        database=settings.SILVER_DB_NAME,
        host=host,
        port=silver_port
    )

    print(f"Connecting to Bronze Database at {host}:{bronze_port}/{settings.BRONZE_DB_NAME}...")
    bronze_conn = await asyncpg.connect(
        user=settings.BRONZE_DB_USER,
        password=settings.BRONZE_DB_PASSWORD,
        database=settings.BRONZE_DB_NAME,
        host=host,
        port=bronze_port
    )

    print(f"Connecting to Gold Database at {host}:{gold_port}/{settings.GOLD_DB_NAME}...")
    gold_conn = await asyncpg.connect(
        user=settings.GOLD_DB_USER,
        password=settings.GOLD_DB_PASSWORD,
        database=settings.GOLD_DB_NAME,
        host=host,
        port=gold_port
    )

    conn = silver_conn
    try:
        print("\n--- Seeding Silver 3NF Catalog (Categories, Authors, Publishers, Books) ---")
        # Categories
        cat_ids = {}
        for cat in ["Computer Science", "Software Architecture", "Mathematics", "Fiction"]:
            row = await conn.fetchrow(
                "INSERT INTO categories (name) VALUES ($1) ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name RETURNING category_id;",
                cat
            )
            cat_ids[cat] = row["category_id"]

        # Authors
        author_ids = {}
        authors_data = [
            ("Robert C. Martin", "unclebob@cleancoder.com"),
            ("Martin Fowler", "martin@martinfowler.com"),
            ("Donald Knuth", "knuth@stanford.edu"),
            ("George Orwell", "orwell@author.org")
        ]
        for name, email in authors_data:
            row = await conn.fetchrow(
                "INSERT INTO authors (name, email) VALUES ($1, $2) ON CONFLICT (name) DO UPDATE SET email=EXCLUDED.email RETURNING author_id;",
                name, email
            )
            author_ids[name] = row["author_id"]

        # Publishers
        pub_ids = {}
        for pub in ["Prentice Hall", "Addison-Wesley", "O'Reilly Media", "Secker & Warburg"]:
            row = await conn.fetchrow(
                "INSERT INTO publishers (name) VALUES ($1) ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name RETURNING publisher_id;",
                pub
            )
            pub_ids[pub] = row["publisher_id"]

        # Books
        books_data = [
            ("Clean Code: A Handbook of Agile Software Craftsmanship", "Robert C. Martin", "Computer Science", "Prentice Hall", "978-0132350884", 42.50, 10),
            ("Clean Architecture: A Craftsman's Guide to Software Structure", "Robert C. Martin", "Software Architecture", "Prentice Hall", "978-0134494166", 39.99, 8),
            ("Refactoring: Improving the Design of Existing Code", "Martin Fowler", "Software Architecture", "Addison-Wesley", "978-0201485677", 47.95, 6),
            ("Patterns of Enterprise Application Architecture", "Martin Fowler", "Software Architecture", "Addison-Wesley", "978-0321127426", 52.00, 5),
            ("The Art of Computer Programming, Vol. 1", "Donald Knuth", "Mathematics", "Addison-Wesley", "978-0201896831", 65.00, 4),
            ("1984", "George Orwell", "Fiction", "Secker & Warburg", "978-0451524935", 14.99, 15),
            ("Animal Farm", "George Orwell", "Fiction", "Secker & Warburg", "978-0451526342", 12.50, 12),
        ]

        book_ids = {}
        for title, author, cat, pub, isbn, price, copies in books_data:
            row = await conn.fetchrow(
                """
                INSERT INTO books (title, author_id, category_id, publisher_id, isbn, price, total_copies, available_copies)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $7)
                ON CONFLICT (isbn) DO UPDATE SET total_copies = EXCLUDED.total_copies, price = EXCLUDED.price
                RETURNING book_id;
                """,
                title, author_ids[author], cat_ids[cat], pub_ids[pub], isbn, price, copies
            )
            book_ids[isbn] = row["book_id"]

        print(f"-> Seeded {len(books_data)} books with full 3NF relationships.")

        # Borrowers & Loans
        print("\n--- Seeding Borrowers, Loans & Fine Records ---")
        borrowers_data = [
            ("STU-1001", "Alice Johnson", "alice@university.edu"),
            ("STU-1002", "Bob Smith", "bob@university.edu"),
            ("STU-1003", "Charlie Davis", "charlie@university.edu"),
            ("STU-1004", "Diana Prince", "diana@university.edu"),
        ]
        borrower_ids = {}
        for sid, name, email in borrowers_data:
            row = await conn.fetchrow(
                """
                INSERT INTO borrowers (student_id, name, email) VALUES ($1, $2, $3)
                ON CONFLICT (student_id) DO UPDATE SET name = EXCLUDED.name, email = EXCLUDED.email
                RETURNING borrower_id;
                """,
                sid, name, email
            )
            borrower_ids[sid] = row["borrower_id"]

        # Add borrow records
        clean_code_id = book_ids["978-0132350884"]
        clean_arch_id = book_ids["978-0134494166"]
        nineteen84_id = book_ids["978-0451524935"]

        now = datetime.now(timezone.utc)
        loans_data = [
            (borrower_ids["STU-1001"], clean_code_id, now - timedelta(days=2), now + timedelta(days=5), None, "BORROWED", 0.0),
            (borrower_ids["STU-1002"], clean_arch_id, now - timedelta(days=15), now - timedelta(days=5), None, "OVERDUE", 25.0),
            (borrower_ids["STU-1003"], nineteen84_id, now - timedelta(days=10), now - timedelta(days=3), now - timedelta(days=1), "RETURNED", 10.0),
        ]

        for b_id, bk_id, b_at, d_at, ret_at, status, fine in loans_data:
            await conn.execute(
                """
                INSERT INTO borrow_records (borrower_id, book_id, borrowed_at, due_date, returned_at, status, fine_amount)
                VALUES ($1, $2, $3, $4, $5, $6, $7);
                """,
                b_id, bk_id, b_at, d_at, ret_at, status, fine
            )
        print("-> Seeded active, overdue, and returned borrow records.")

        # Seed Book Views
        for b_id in [clean_code_id, clean_arch_id, nineteen84_id]:
            for u in ["STU-1001", "STU-1002", "ANONYMOUS"]:
                await conn.execute(
                    "INSERT INTO book_views (book_id, user_identifier, viewed_at) VALUES ($1, $2, $3);",
                    b_id, u, now - timedelta(hours=2)
                )
        print("-> Seeded sample book views.")

        # Bronze raw staging
        print("\n--- Seeding Raw Bronze Ingest Data (for testing Medallion ETL) ---")
        bronze_payloads = [
            {
                "title": "Designing Data-Intensive Applications",
                "author": "Martin Kleppmann",
                "category": "Computer Science",
                "publisher": "O'Reilly Media",
                "isbn": "978-1449373320",
                "price": 49.99,
                "total_copies": 3
            },
            {
                "title": "Domain-Driven Design",
                "author": "Eric Evans",
                "category": "Software Architecture",
                "publisher": "Addison-Wesley",
                "isbn": "978-0321125217",
                "price": 54.00,
                "total_copies": 2
            }
        ]

        for payload in bronze_payloads:
            await bronze_conn.execute(
                """
                INSERT INTO bronze_books_ingest (raw_payload, source_channel, processed_flag)
                VALUES ($1::jsonb, 'TEST_SEED', FALSE);
                """,
                json.dumps(payload)
            )
        print(f"-> Seeded {len(bronze_payloads)} unprocessed records into bronze_books_ingest on Bronze Database.")

        # Seed sample Gold aggregations
        today = datetime.now(timezone.utc).date()
        await gold_conn.execute("""
            INSERT INTO gold_loans_returns_daily (summary_date, total_loans, total_returns, total_overdue, total_fines_accrued, total_fines_collected)
            VALUES ($1, 3, 1, 1, 35.00, 10.00)
            ON CONFLICT (summary_date) DO UPDATE SET total_loans=EXCLUDED.total_loans;
        """, today)

        await gold_conn.execute("""
            INSERT INTO gold_book_views_daily (summary_date, book_id, book_title, category_name, total_views, unique_users)
            VALUES ($1, $2, 'Clean Code', 'Computer Science', 15, 6)
            ON CONFLICT (summary_date, book_id) DO UPDATE SET total_views=EXCLUDED.total_views;
        """, today, clean_code_id)

        print("-> Seeded sample aggregations in Gold Database.")
        print("\n[SUCCESS] Test data successfully seeded across Bronze, Silver, and Gold databases!")

    finally:
        await silver_conn.close()
        await bronze_conn.close()
        await gold_conn.close()

if __name__ == "__main__":
    asyncio.run(seed_data())
