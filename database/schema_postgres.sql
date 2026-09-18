-- ============================================================================
-- Enterprise Medallion Data Architecture (PostgreSQL 16)
-- High-Throughput Decoupled Library Management System (~1000 req/sec)
-- Layer Structure: LANDING -> BRONZE -> SILVER (3NF OLTP) -> GOLD (OLAP Analytics)
-- ============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- 1. LANDING LAYER (Raw Data Staging & Async Ingestion)
-- ============================================================================

CREATE TABLE IF NOT EXISTS landing_books_ingest (
    ingest_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    raw_payload JSONB NOT NULL,
    source_channel VARCHAR(50) DEFAULT 'API',
    received_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    processed_flag BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS landing_borrow_ingest (
    ingest_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    raw_payload JSONB NOT NULL,
    source_channel VARCHAR(50) DEFAULT 'API',
    received_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    processed_flag BOOLEAN DEFAULT FALSE
);

-- ============================================================================
-- 2. BRONZE LAYER (Raw Cleaned, Sanitized Snapshot & Audit History)
-- ============================================================================

CREATE TABLE IF NOT EXISTS bronze_books (
    bronze_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ingest_id UUID REFERENCES landing_books_ingest(ingest_id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    author_name VARCHAR(255) NOT NULL,
    category_name VARCHAR(100) DEFAULT 'General',
    publisher_name VARCHAR(255) DEFAULT 'Unknown Publisher',
    isbn VARCHAR(20),
    price NUMERIC(8, 2) DEFAULT 0.00,
    total_copies INT DEFAULT 1,
    bronze_ingested_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_valid BOOLEAN DEFAULT TRUE,
    validation_notes TEXT
);

CREATE TABLE IF NOT EXISTS bronze_borrow_records (
    bronze_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ingest_id UUID REFERENCES landing_borrow_ingest(ingest_id) ON DELETE SET NULL,
    borrower_name VARCHAR(255) NOT NULL,
    student_id VARCHAR(50) NOT NULL,
    email VARCHAR(255),
    book_title VARCHAR(255) NOT NULL,
    isbn VARCHAR(20),
    borrow_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    due_date TIMESTAMP WITH TIME ZONE,
    bronze_ingested_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_valid BOOLEAN DEFAULT TRUE,
    validation_notes TEXT
);

CREATE TABLE IF NOT EXISTS bronze_ingestion_errors (
    error_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_layer VARCHAR(20) NOT NULL, -- 'LANDING' or 'BRONZE'
    raw_data JSONB,
    error_message TEXT NOT NULL,
    logged_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Unique constraints required for ON CONFLICT (ingest_id) idempotency
CREATE UNIQUE INDEX IF NOT EXISTS idx_bronze_books_ingest_id ON bronze_books(ingest_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bronze_borrow_ingest_id ON bronze_borrow_records(ingest_id);

-- ============================================================================
-- 3. SILVER LAYER (Operational 3NF Normalized OLTP System)
-- ============================================================================

CREATE TABLE IF NOT EXISTS categories (
    category_id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS authors (
    author_id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS publishers (
    publisher_id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    address TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS books (
    book_id SERIAL PRIMARY KEY,
    isbn VARCHAR(20) UNIQUE,
    title VARCHAR(255) NOT NULL,
    author_id INT NOT NULL REFERENCES authors(author_id) ON DELETE RESTRICT,
    category_id INT NOT NULL REFERENCES categories(category_id) ON DELETE RESTRICT,
    publisher_id INT NOT NULL REFERENCES publishers(publisher_id) ON DELETE RESTRICT,
    price NUMERIC(8, 2) NOT NULL CHECK (price >= 0),
    total_copies INT NOT NULL DEFAULT 1 CHECK (total_copies >= 0),
    available_copies INT NOT NULL DEFAULT 1 CHECK (available_copies >= 0),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_copies CHECK (available_copies <= total_copies)
);

CREATE TABLE IF NOT EXISTS borrowers (
    borrower_id SERIAL PRIMARY KEY,
    student_id VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    status VARCHAR(20) DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'SUSPENDED', 'GRADUATED')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS borrow_records (
    record_id SERIAL PRIMARY KEY,
    borrower_id INT NOT NULL REFERENCES borrowers(borrower_id) ON DELETE RESTRICT,
    book_id INT NOT NULL REFERENCES books(book_id) ON DELETE RESTRICT,
    borrowed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    due_date TIMESTAMP WITH TIME ZONE NOT NULL,
    returned_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR(20) DEFAULT 'BORROWED' CHECK (status IN ('BORROWED', 'RETURNED', 'OVERDUE', 'LOST')),
    fine_amount NUMERIC(8, 2) DEFAULT 0.00 CHECK (fine_amount >= 0),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fine_payments (
    payment_id SERIAL PRIMARY KEY,
    record_id INT NOT NULL REFERENCES borrow_records(record_id) ON DELETE RESTRICT,
    amount NUMERIC(8, 2) NOT NULL CHECK (amount > 0),
    paid_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    payment_method VARCHAR(50) DEFAULT 'CASH'
);

-- B-Tree Performance Indexes for Sub-Millisecond Lookups
CREATE INDEX IF NOT EXISTS idx_books_isbn ON books(isbn);
CREATE INDEX IF NOT EXISTS idx_books_title ON books(title);
CREATE INDEX IF NOT EXISTS idx_books_author_cat ON books(author_id, category_id);
CREATE INDEX IF NOT EXISTS idx_borrowers_student_id ON borrowers(student_id);
CREATE INDEX IF NOT EXISTS idx_borrow_records_due_status ON borrow_records(due_date, status);
CREATE INDEX IF NOT EXISTS idx_borrow_records_borrower_id ON borrow_records(borrower_id);
CREATE INDEX IF NOT EXISTS idx_borrow_records_book_id ON borrow_records(book_id);
CREATE INDEX IF NOT EXISTS idx_books_updated_at ON books(updated_at);
CREATE INDEX IF NOT EXISTS idx_borrow_records_updated_at ON borrow_records(updated_at);

-- Automatic `updated_at` Trigger Function
CREATE OR REPLACE FUNCTION update_timestamp_column()
RETURNS TRIGGER AS $$
BEGIN
   NEW.updated_at = CURRENT_TIMESTAMP;
   RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_update_books_timestamp
    BEFORE UPDATE ON books
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp_column();

CREATE OR REPLACE TRIGGER trg_update_borrowers_timestamp
    BEFORE UPDATE ON borrowers
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp_column();

CREATE OR REPLACE TRIGGER trg_update_borrow_records_timestamp
    BEFORE UPDATE ON borrow_records
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp_column();

-- ============================================================================
-- 4. GOLD LAYER (Aggregated Enterprise Analytics & Reporting Data Marts)
-- ============================================================================

CREATE TABLE IF NOT EXISTS gold_daily_kpi_summary (
    summary_date DATE PRIMARY KEY,
    total_books_in_catalog INT DEFAULT 0,
    total_copies_available INT DEFAULT 0,
    total_active_loans INT DEFAULT 0,
    total_overdue_loans INT DEFAULT 0,
    total_fines_accrued NUMERIC(10, 2) DEFAULT 0.00,
    total_fines_collected NUMERIC(10, 2) DEFAULT 0.00,
    last_updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE OR REPLACE VIEW vw_gold_inventory_status AS
SELECT 
    b.book_id,
    b.isbn,
    b.title,
    a.name AS author_name,
    c.name AS category_name,
    p.name AS publisher_name,
    b.price,
    b.total_copies,
    b.available_copies,
    (b.total_copies - b.available_copies) AS borrowed_copies,
    CASE 
        WHEN b.available_copies = 0 THEN 'OUT_OF_STOCK'
        WHEN b.available_copies < 3 THEN 'LOW_STOCK'
        ELSE 'AVAILABLE'
    END AS stock_status
FROM books b
JOIN authors a ON b.author_id = a.author_id
JOIN categories c ON b.category_id = c.category_id
JOIN publishers p ON b.publisher_id = p.publisher_id;

CREATE OR REPLACE VIEW vw_gold_overdue_fines AS
SELECT 
    br.record_id,
    bw.student_id,
    bw.name AS borrower_name,
    bw.email AS borrower_email,
    bk.title AS book_title,
    br.borrowed_at,
    br.due_date,
    br.returned_at,
    br.status,
    GREATEST(0, EXTRACT(DAY FROM (COALESCE(br.returned_at, CURRENT_TIMESTAMP) - br.due_date)))::INT AS days_overdue,
    (GREATEST(0, EXTRACT(DAY FROM (COALESCE(br.returned_at, CURRENT_TIMESTAMP) - br.due_date)))::INT * 5.00)::NUMERIC(8,2) AS calculated_fine
FROM borrow_records br
JOIN borrowers bw ON br.borrower_id = bw.borrower_id
JOIN books bk ON br.book_id = bk.book_id
WHERE br.due_date < CURRENT_TIMESTAMP AND br.status IN ('BORROWED', 'OVERDUE');

CREATE OR REPLACE VIEW vw_gold_author_popularity AS
SELECT 
    a.author_id,
    a.name AS author_name,
    COUNT(br.record_id) AS total_times_borrowed,
    COUNT(DISTINCT bk.book_id) AS total_books_published
FROM authors a
LEFT JOIN books bk ON a.author_id = bk.author_id
LEFT JOIN borrow_records br ON bk.book_id = br.book_id
GROUP BY a.author_id, a.name;

-- ============================================================================
-- 5. ATOMIC STORED PROCEDURES (Row-Level Locking & High-Concurrency Isolation)
-- ============================================================================

-- Procedure: Issue Book Atomically
CREATE OR REPLACE FUNCTION sp_issue_book(
    p_student_id VARCHAR(50),
    p_borrower_name VARCHAR(255),
    p_book_title VARCHAR(255),
    p_loan_days INT DEFAULT 7
) RETURNS TABLE (
    success BOOLEAN,
    message TEXT,
    record_id INT,
    due_date TIMESTAMP WITH TIME ZONE
) AS $$
DECLARE
    v_borrower_id INT;
    v_book_id INT;
    v_avail_copies INT;
    v_new_record_id INT;
    v_due_date TIMESTAMP WITH TIME ZONE;
BEGIN
    -- 1. Ensure Borrower exists or create atomically (ON CONFLICT DO UPDATE) to prevent race conditions
    INSERT INTO borrowers (student_id, name)
    VALUES (p_student_id, p_borrower_name)
    ON CONFLICT (student_id) DO UPDATE SET name = EXCLUDED.name
    RETURNING borrower_id INTO v_borrower_id;

    -- 2. Select Book with ROW-LEVEL LOCK (FOR UPDATE) to prevent race conditions
    SELECT book_id, available_copies INTO v_book_id, v_avail_copies
    FROM books
    WHERE LOWER(title) = LOWER(p_book_title) OR isbn = p_book_title
    ORDER BY available_copies DESC
    LIMIT 1
    FOR UPDATE;

    IF v_book_id IS NULL THEN
        RETURN QUERY SELECT FALSE, 'Book not found in inventory.'::TEXT, NULL::INT, NULL::TIMESTAMP WITH TIME ZONE;
        RETURN;
    END IF;

    IF v_avail_copies <= 0 THEN
        RETURN QUERY SELECT FALSE, 'Book is currently out of stock.'::TEXT, NULL::INT, NULL::TIMESTAMP WITH TIME ZONE;
        RETURN;
    END IF;

    -- 3. Decrement available copies & Record Loan
    UPDATE books SET available_copies = available_copies - 1 WHERE book_id = v_book_id;
    
    v_due_date := CURRENT_TIMESTAMP + (p_loan_days || ' days')::INTERVAL;

    INSERT INTO borrow_records (borrower_id, book_id, due_date, status)
    VALUES (v_borrower_id, v_book_id, v_due_date, 'BORROWED')
    RETURNING borrow_records.record_id INTO v_new_record_id;

    RETURN QUERY SELECT TRUE, 'Book issued successfully.'::TEXT, v_new_record_id, v_due_date;
END;
$$ LANGUAGE plpgsql;

-- Procedure: Return Book Atomically
CREATE OR REPLACE FUNCTION sp_return_book(
    p_record_id INT
) RETURNS TABLE (
    success BOOLEAN,
    message TEXT,
    returned_at TIMESTAMP WITH TIME ZONE,
    fine_amount NUMERIC(8, 2)
) AS $$
DECLARE
    v_book_id INT;
    v_due_date TIMESTAMP WITH TIME ZONE;
    v_status VARCHAR(20);
    v_returned_at TIMESTAMP WITH TIME ZONE;
    v_days_overdue INT;
    v_fine NUMERIC(8, 2) := 0.00;
BEGIN
    -- Select record with FOR UPDATE
    SELECT book_id, due_date, status INTO v_book_id, v_due_date, v_status
    FROM borrow_records
    WHERE record_id = p_record_id
    FOR UPDATE;

    IF v_book_id IS NULL THEN
        RETURN QUERY SELECT FALSE, 'Borrow record not found.'::TEXT, NULL::TIMESTAMP WITH TIME ZONE, 0.00::NUMERIC(8,2);
        RETURN;
    END IF;

    IF v_status = 'RETURNED' THEN
        RETURN QUERY SELECT FALSE, 'Book has already been returned.'::TEXT, NULL::TIMESTAMP WITH TIME ZONE, 0.00::NUMERIC(8,2);
        RETURN;
    END IF;

    v_returned_at := CURRENT_TIMESTAMP;
    
    -- Calculate fine ($5 per overdue day)
    IF v_returned_at > v_due_date THEN
        v_days_overdue := EXTRACT(DAY FROM (v_returned_at - v_due_date))::INT;
        v_fine := (v_days_overdue * 5.00)::NUMERIC(8,2);
    END IF;

    -- Update record & Increment book copies atomically
    UPDATE borrow_records 
    SET returned_at = v_returned_at,
        status = 'RETURNED',
        fine_amount = v_fine
    WHERE record_id = p_record_id;

    UPDATE books SET available_copies = available_copies + 1 WHERE book_id = v_book_id;

    RETURN QUERY SELECT TRUE, 'Book returned successfully.'::TEXT, v_returned_at, v_fine;
END;
$$ LANGUAGE plpgsql;

-- Procedure: Medallion Refresh Gold Analytics
CREATE OR REPLACE FUNCTION sp_refresh_gold_analytics()
RETURNS VOID AS $$
BEGIN
    INSERT INTO gold_daily_kpi_summary (
        summary_date,
        total_books_in_catalog,
        total_copies_available,
        total_active_loans,
        total_overdue_loans,
        total_fines_accrued,
        total_fines_collected,
        last_updated_at
    )
    SELECT
        CURRENT_DATE,
        (SELECT COUNT(*) FROM books),
        (SELECT COALESCE(SUM(available_copies), 0) FROM books),
        (SELECT COUNT(*) FROM borrow_records WHERE status = 'BORROWED'),
        (SELECT COUNT(*) FROM borrow_records WHERE status = 'OVERDUE' OR (status = 'BORROWED' AND due_date < CURRENT_TIMESTAMP)),
        (SELECT COALESCE(SUM(fine_amount), 0.00) FROM borrow_records),
        (SELECT COALESCE(SUM(amount), 0.00) FROM fine_payments),
        CURRENT_TIMESTAMP
    ON CONFLICT (summary_date) DO UPDATE SET
        total_books_in_catalog = EXCLUDED.total_books_in_catalog,
        total_copies_available = EXCLUDED.total_copies_available,
        total_active_loans = EXCLUDED.total_active_loans,
        total_overdue_loans = EXCLUDED.total_overdue_loans,
        total_fines_accrued = EXCLUDED.total_fines_accrued,
        total_fines_collected = EXCLUDED.total_fines_collected,
        last_updated_at = EXCLUDED.last_updated_at;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 5. PIPELINE EXECUTION AUDIT HISTORY
-- ============================================================================

CREATE TABLE IF NOT EXISTS library_pipelinerunhistory (
    id SERIAL PRIMARY KEY,
    mode VARCHAR(50) NOT NULL DEFAULT 'landing_to_bronze',
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    ended_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR(20) NOT NULL DEFAULT 'RUNNING',
    rows_landing_to_bronze INT NOT NULL DEFAULT 0,
    rows_bronze_to_silver INT NOT NULL DEFAULT 0,
    gold_refreshed BOOLEAN NOT NULL DEFAULT FALSE,
    error_message TEXT
);
