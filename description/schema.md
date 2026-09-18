# 3NF Relational Database Schema & Data Dictionary

## 1. Entity-Relationship Diagram (3NF Silver Layer)

```
   ┌──────────────┐          ┌──────────────┐          ┌──────────────┐
   │  categories  │          │   authors    │          │  publishers  │
   ├──────────────┤          ├──────────────┤          ├──────────────┤
   │ PK category_id│         │ PK author_id │          │ PK publisher_id│
   │    name      │          │    name      │          │    name      │
   └──────┬───────┘          └──────┬───────┘          └──────┬───────┘
          │ 1                       │ 1                       │ 1
          │                         │                         │
          └─────────────────────────┼─────────────────────────┘
                                    │ N
                             ┌──────▼───────┐
                             │    books     │
                             ├──────────────┤
                             │ PK book_id   │
                             │ FK author_id │
                             │ FK category_id│
                             │ FK publisher_id│
                             │    isbn      │
                             │    title     │
                             │    price     │
                             │ total_copies │
                             │available_copies│
                             └──────┬───────┘
                                    │ 1
                                    │ N
                             ┌──────▼───────┐          ┌──────────────┐
                             │borrow_records│   N    1 │  borrowers   │
                             ├──────────────┼──────────┤──────────────┤
                             │ PK record_id │          │ PK borrower_id│
                             │ FK book_id   │          │    student_id│
                             │ FK borrower_id│         │    name      │
                             │  borrowed_at │          │    status    │
                             │   due_date   │          └──────────────┘
                             │  returned_at │
                             │    status    │
                             │  fine_amount │
                             └──────┬───────┘
                                    │ 1
                                    │ N
                             ┌──────▼───────┐
                             │ fine_payments│
                             ├──────────────┤
                             │ PK payment_id│
                             │ FK record_id │
                             │    amount    │
                             └──────────────┘
```

---

## 2. Silver Layer Table Specifications (3NF Normalized)

### 2.1 `categories` Table
- `category_id` (SERIAL / INT AUTO_INCREMENT, Primary Key)
- `name` (VARCHAR(100), UNIQUE, NOT NULL)
- `description` (TEXT, Nullable)
- `created_at` (TIMESTAMP WITH TIME ZONE, DEFAULT CURRENT_TIMESTAMP)

### 2.2 `authors` Table
- `author_id` (SERIAL / INT AUTO_INCREMENT, Primary Key)
- `name` (VARCHAR(255), UNIQUE, NOT NULL)
- `email` (VARCHAR(255), Nullable)
- `created_at` (TIMESTAMP WITH TIME ZONE, DEFAULT CURRENT_TIMESTAMP)

### 2.3 `publishers` Table
- `publisher_id` (SERIAL / INT AUTO_INCREMENT, Primary Key)
- `name` (VARCHAR(255), UNIQUE, NOT NULL)
- `address` (TEXT, Nullable)
- `created_at` (TIMESTAMP WITH TIME ZONE, DEFAULT CURRENT_TIMESTAMP)

### 2.4 `books` Table (3NF Normalized Inventory)
- `book_id` (SERIAL / INT AUTO_INCREMENT, Primary Key)
- `isbn` (VARCHAR(20), UNIQUE, Nullable)
- `title` (VARCHAR(255), NOT NULL)
- `author_id` (INT, FK -> `authors.author_id`, ON DELETE RESTRICT)
- `category_id` (INT, FK -> `categories.category_id`, ON DELETE RESTRICT)
- `publisher_id` (INT, FK -> `publishers.publisher_id`, ON DELETE RESTRICT)
- `price` (NUMERIC(8,2), CHECK `price >= 0`)
- `total_copies` (INT, DEFAULT 1, CHECK `total_copies >= 0`)
- `available_copies` (INT, DEFAULT 1, CHECK `available_copies >= 0`)
- `created_at` (TIMESTAMP WITH TIME ZONE, DEFAULT CURRENT_TIMESTAMP)
- `updated_at` (TIMESTAMP WITH TIME ZONE, DEFAULT CURRENT_TIMESTAMP)
- *Constraint*: `chk_copies CHECK (available_copies <= total_copies)`

### 2.5 `borrowers` Table
- `borrower_id` (SERIAL / INT AUTO_INCREMENT, Primary Key)
- `student_id` (VARCHAR(50), UNIQUE, NOT NULL)
- `name` (VARCHAR(255), NOT NULL)
- `email` (VARCHAR(255), Nullable)
- `status` (VARCHAR(20), DEFAULT 'ACTIVE', CHECK `status IN ('ACTIVE', 'SUSPENDED', 'GRADUATED')`)
- `created_at` (TIMESTAMP WITH TIME ZONE, DEFAULT CURRENT_TIMESTAMP)
- `updated_at` (TIMESTAMP WITH TIME ZONE, DEFAULT CURRENT_TIMESTAMP)

### 2.6 `borrow_records` Table
- `record_id` (SERIAL / INT AUTO_INCREMENT, Primary Key)
- `borrower_id` (INT, FK -> `borrowers.borrower_id`, ON DELETE RESTRICT)
- `book_id` (INT, FK -> `books.book_id`, ON DELETE RESTRICT)
- `borrowed_at` (TIMESTAMP WITH TIME ZONE, DEFAULT CURRENT_TIMESTAMP)
- `due_date` (TIMESTAMP WITH TIME ZONE, NOT NULL)
- `returned_at` (TIMESTAMP WITH TIME ZONE, Nullable)
- `status` (VARCHAR(20), DEFAULT 'BORROWED', CHECK `status IN ('BORROWED', 'RETURNED', 'OVERDUE', 'LOST')`)
- `fine_amount` (NUMERIC(8,2), DEFAULT 0.00, CHECK `fine_amount >= 0`)
- `updated_at` (TIMESTAMP WITH TIME ZONE, DEFAULT CURRENT_TIMESTAMP)

### 2.7 `fine_payments` Table
- `payment_id` (SERIAL / INT AUTO_INCREMENT, Primary Key)
- `record_id` (INT, FK -> `borrow_records.record_id`, ON DELETE RESTRICT)
- `amount` (NUMERIC(8,2), CHECK `amount > 0`)
- `paid_at` (TIMESTAMP WITH TIME ZONE, DEFAULT CURRENT_TIMESTAMP)
- `payment_method` (VARCHAR(50), DEFAULT 'CASH')

---

## 3. B-Tree Performance Indexing

- `idx_books_isbn`: Accelerates ISBN-based catalog queries.
- `idx_books_title`: Speeds up title search & exact matching during checkout.
- `idx_books_author_cat`: Optimizes composite catalog filtering by author and category.
- `idx_borrowers_student_id`: Speeds up student identification lookup during loan issuance.
- `idx_borrow_records_due_status`: Accelerates overdue calculation views and daily fine background processing.
- `idx_borrow_records_borrower_id` & `idx_borrow_records_book_id`: Speeds up foreign key join operations.

---

## 4. Database Views & Stored Procedures

### A. Database Views
1. `vw_gold_inventory_status`: Detailed inventory catalog join with calculated `borrowed_copies` and `stock_status` ('OUT_OF_STOCK', 'LOW_STOCK', 'AVAILABLE').
2. `vw_gold_overdue_fines`: Overdue loan analysis with calculated `days_overdue` and estimated fine amount ($5.00/day).
3. `vw_gold_author_popularity`: Author analytics tracking total times borrowed and published book count.

### B. Atomic Stored Procedures
1. `sp_issue_book(p_student_id, p_borrower_name, p_book_title, p_loan_days)`:
   - Performs atomic borrower registration.
   - Locks target book row (`FOR UPDATE`).
   - Verifies available stock (`available_copies > 0`).
   - Decrements stock and inserts loan record atomically.
2. `sp_return_book(p_record_id)`:
   - Locks loan record (`FOR UPDATE`).
   - Computes overdue days and fine amount.
   - Sets `returned_at`, `status = 'RETURNED'`, and increments `available_copies` atomically.
3. `sp_refresh_gold_analytics()`:
   - Aggregates daily KPI metrics into `gold_daily_kpi_summary`.
