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
    print(f"Connecting to PostgreSQL at {settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}...")
    conn = await asyncpg.connect(
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        database=settings.POSTGRES_DB,
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT
    )

    try:
        print("\n--- Seeding Silver 3NF Catalog (Categories, Authors, Publishers, Books) ---")
        # Categories
        cat_ids = {}
        for cat in ["Computer Science", "Software Architecture", "Mathematics", "Fiction"]:
            row = await conn.fetchrow(
                "INSERT INTO categories (name) VALUES ($1) ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING category_id;",
                cat
            )
            cat_ids[cat] = row["category_id"]

        # Authors
        author_ids = {}
        for author, email in [
            ("Robert C. Martin", "unclebob@example.com"),
            ("Martin Fowler", "fowler@example.com"),
            ("Andrew Hunt", "andy@pragprog.com"),
            ("Donald Knuth", "knuth@stanford.edu"),
            ("Eric Evans", "evans@domainlanguage.com"),
            ("Martin Kleppmann", "martin@kleppmann.com"),
            ("Joshua Bloch", "bloch@java.com"),
            ("Brian Goetz", "brian@concurrency.com"),
            ("Michael Nygard", "nygard@releaseit.com"),
            ("Gene Kim", "gene@itrevolution.com"),
            ("John Ousterhout", "john@stanford.edu"),
            ("Kyle Simpson", "kyle@getify.com"),
        ]:
            row = await conn.fetchrow(
                "INSERT INTO authors (name, email) VALUES ($1, $2) ON CONFLICT (name) DO UPDATE SET email = EXCLUDED.email RETURNING author_id;",
                author, email
            )
            author_ids[author] = row["author_id"]

        # Publishers
        pub_ids = {}
        for pub, addr in [
            ("Prentice Hall", "Upper Saddle River, NJ"),
            ("Addison-Wesley", "Boston, MA"),
            ("O'Reilly Media", "Sebastopol, CA"),
            ("Pragmatic Bookshelf", "Raleigh, NC"),
            ("IT Revolution", "Portland, OR"),
        ]:
            row = await conn.fetchrow(
                "INSERT INTO publishers (name, address) VALUES ($1, $2) ON CONFLICT (name) DO UPDATE SET address = EXCLUDED.address RETURNING publisher_id;",
                pub, addr
            )
            pub_ids[pub] = row["publisher_id"]

        # Books
        sample_books = [
            ("978-0132350884", "Clean Code", "Robert C. Martin", "Computer Science", "Prentice Hall", 42.50, 5, 4),
            ("978-0201485677", "Refactoring", "Martin Fowler", "Software Architecture", "Addison-Wesley", 47.99, 4, 3),
            ("978-0201616224", "The Pragmatic Programmer", "Andrew Hunt", "Computer Science", "Addison-Wesley", 45.00, 6, 6),
            ("978-0201896831", "The Art of Computer Programming", "Donald Knuth", "Mathematics", "Addison-Wesley", 85.00, 2, 2),
            ("978-0321125217", "Domain-Driven Design", "Eric Evans", "Software Architecture", "Addison-Wesley", 54.00, 4, 3),
            ("978-1449373320", "Designing Data-Intensive Applications", "Martin Kleppmann", "Computer Science", "O'Reilly Media", 49.99, 5, 5),
            ("978-0134685991", "Effective Java", "Joshua Bloch", "Computer Science", "Addison-Wesley", 44.50, 6, 5),
            ("978-0321349606", "Java Concurrency in Practice", "Brian Goetz", "Computer Science", "Addison-Wesley", 52.00, 4, 4),
            ("978-0997148008", "The Phoenix Project", "Gene Kim", "Software Architecture", "IT Revolution", 29.99, 7, 6),
            ("978-1942788331", "The DevOps Handbook", "Gene Kim", "Software Architecture", "IT Revolution", 34.95, 5, 5),
            ("978-0984782857", "Cracking the Coding Interview", "Joshua Bloch", "Computer Science", "Prentice Hall", 39.99, 10, 8),
            ("978-1984877109", "A Philosophy of Software Design", "John Ousterhout", "Software Architecture", "Pragmatic Bookshelf", 28.50, 6, 5),
            ("978-1491904244", "You Don't Know JS: Scope & Closures", "Kyle Simpson", "Computer Science", "O'Reilly Media", 24.99, 5, 5),
            ("978-1491904152", "You Don't Know JS: Async & Performance", "Kyle Simpson", "Computer Science", "O'Reilly Media", 26.50, 4, 4),
            ("978-0137081073", "The Clean Coder", "Robert C. Martin", "Computer Science", "Prentice Hall", 38.00, 5, 4),
            ("978-0134494166", "Clean Architecture", "Robert C. Martin", "Software Architecture", "Prentice Hall", 41.50, 8, 7),
            ("978-0997148015", "Accelerate: Building High Performing Tech", "Gene Kim", "Software Architecture", "IT Revolution", 27.00, 6, 6),
            ("978-0321601919", "Continuous Delivery", "Martin Fowler", "Software Architecture", "Addison-Wesley", 49.00, 5, 4),
            ("978-0134757599", "Refactoring: Improving the Design of Existing Code", "Martin Fowler", "Software Architecture", "Addison-Wesley", 51.00, 5, 5),
            ("978-1680502398", "Release It! 2nd Edition", "Michael Nygard", "Software Architecture", "Pragmatic Bookshelf", 42.00, 4, 3),
            ("978-0135974445", "The Pragmatic Programmer: 20th Anniversary", "Andrew Hunt", "Computer Science", "Addison-Wesley", 49.95, 8, 7),
        ]

        book_ids = {}
        for isbn, title, author, cat, pub, price, total, avail in sample_books:
            row = await conn.fetchrow(
                """
                INSERT INTO books (isbn, title, author_id, category_id, publisher_id, price, total_copies, available_copies)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (isbn) DO UPDATE SET 
                    total_copies = EXCLUDED.total_copies, 
                    available_copies = EXCLUDED.available_copies
                RETURNING book_id;
                """,
                isbn, title, author_ids[author], cat_ids[cat], pub_ids[pub], price, total, avail
            )
            book_ids[title] = row["book_id"]
        print(f"-> Seeded {len(sample_books)} books into Silver catalog.")

        print("\n--- Seeding Borrowers & Loans ---")
        students = [
            ("STU-1001", "Alice Smith", "alice@university.edu"),
            ("STU-1002", "Bob Johnson", "bob@university.edu"),
            ("STU-1003", "Charlie Davis", "charlie@university.edu")
        ]
        borrower_ids = {}
        for sid, name, email in students:
            row = await conn.fetchrow(
                """
                INSERT INTO borrowers (student_id, name, email)
                VALUES ($1, $2, $3)
                ON CONFLICT (student_id) DO UPDATE SET name = EXCLUDED.name
                RETURNING borrower_id;
                """,
                sid, name, email
            )
            borrower_ids[sid] = row["borrower_id"]

        now = datetime.now(timezone.utc)
        loans = [
            # 1. Active current loan (Due in 5 days)
            (borrower_ids["STU-1001"], book_ids["Clean Code"], now - timedelta(days=2), now + timedelta(days=5), None, "BORROWED", 0.00),
            # 2. Overdue loan (Due 4 days ago)
            (borrower_ids["STU-1002"], book_ids["Refactoring"], now - timedelta(days=11), now - timedelta(days=4), None, "OVERDUE", 8.00),
            # 3. Returned loan
            (borrower_ids["STU-1003"], book_ids["The Pragmatic Programmer"], now - timedelta(days=15), now - timedelta(days=8), now - timedelta(days=7), "RETURNED", 0.00),
        ]

        for b_id, bk_id, b_at, d_at, ret_at, status, fine in loans:
            await conn.execute(
                """
                INSERT INTO borrow_records (borrower_id, book_id, borrowed_at, due_date, returned_at, status, fine_amount)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT DO NOTHING;
                """,
                b_id, bk_id, b_at, d_at, ret_at, status, fine
            )
        print("-> Seeded active, overdue, and returned borrow records.")

        print("\n--- Seeding Raw Landing Ingest Data (for testing Medallion ETL) ---")
        landing_payloads = [
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

        for payload in landing_payloads:
            await conn.execute(
                """
                INSERT INTO landing_books_ingest (raw_payload, source_channel, processed_flag)
                VALUES ($1::jsonb, 'TEST_SEED', FALSE);
                """,
                json.dumps(payload)
            )
        print(f"-> Seeded {len(landing_payloads)} unprocessed records into landing_books_ingest.")

        # Refresh Gold layer
        print("\n--- Refreshing Gold Layer Analytics ---")
        await conn.execute("SELECT sp_refresh_gold_analytics();")
        print("-> Gold KPI summary refreshed.")

        print("\n[SUCCESS] Test data successfully seeded into database!")

    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(seed_data())
