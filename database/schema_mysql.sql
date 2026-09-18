-- ============================================================================
-- Enterprise Medallion Data Architecture (MySQL 8.0)
-- High-Throughput Decoupled Library Management System (~1000 req/sec)
-- Layer Structure: LANDING -> BRONZE -> SILVER (3NF OLTP) -> GOLD (OLAP Analytics)
-- ============================================================================

CREATE DATABASE IF NOT EXISTS library_db;
USE library_db;

-- ============================================================================
-- 1. LANDING LAYER (Raw Data Staging & Async Ingestion)
-- ============================================================================

CREATE TABLE IF NOT EXISTS landing_books_ingest (
    ingest_id VARCHAR(36) PRIMARY KEY,
    raw_payload JSON NOT NULL,
    source_channel VARCHAR(50) DEFAULT 'API',
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_flag BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS landing_borrow_ingest (
    ingest_id VARCHAR(36) PRIMARY KEY,
    raw_payload JSON NOT NULL,
    source_channel VARCHAR(50) DEFAULT 'API',
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_flag BOOLEAN DEFAULT FALSE
);

-- ============================================================================
-- 2. BRONZE LAYER (Sanitized Snapshot & Audit History)
-- ============================================================================

CREATE TABLE IF NOT EXISTS bronze_books (
    bronze_id VARCHAR(36) PRIMARY KEY,
    ingest_id VARCHAR(36),
    title VARCHAR(255) NOT NULL,
    author_name VARCHAR(255) NOT NULL,
    category_name VARCHAR(100) DEFAULT 'General',
    publisher_name VARCHAR(255) DEFAULT 'Unknown Publisher',
    isbn VARCHAR(20),
    price DECIMAL(8, 2) DEFAULT 0.00,
    total_copies INT DEFAULT 1,
    bronze_ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_valid BOOLEAN DEFAULT TRUE,
    validation_notes TEXT,
    FOREIGN KEY (ingest_id) REFERENCES landing_books_ingest(ingest_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS bronze_borrow_records (
    bronze_id VARCHAR(36) PRIMARY KEY,
    ingest_id VARCHAR(36),
    borrower_name VARCHAR(255) NOT NULL,
    student_id VARCHAR(50) NOT NULL,
    email VARCHAR(255),
    book_title VARCHAR(255) NOT NULL,
    isbn VARCHAR(20),
    borrow_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    due_date TIMESTAMP NULL,
    bronze_ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_valid BOOLEAN DEFAULT TRUE,
    validation_notes TEXT,
    FOREIGN KEY (ingest_id) REFERENCES landing_borrow_ingest(ingest_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS bronze_ingestion_errors (
    error_id VARCHAR(36) PRIMARY KEY,
    source_layer VARCHAR(20) NOT NULL,
    raw_data JSON,
    error_message TEXT NOT NULL,
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 3. SILVER LAYER (Operational 3NF Normalized OLTP System)
-- ============================================================================

CREATE TABLE IF NOT EXISTS categories (
    category_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS authors (
    author_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS publishers (
    publisher_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS books (
    book_id INT AUTO_INCREMENT PRIMARY KEY,
    isbn VARCHAR(20) UNIQUE,
    title VARCHAR(255) NOT NULL,
    author_id INT NOT NULL,
    category_id INT NOT NULL,
    publisher_id INT NOT NULL,
    price DECIMAL(8, 2) NOT NULL CHECK (price >= 0),
    total_copies INT NOT NULL DEFAULT 1 CHECK (total_copies >= 0),
    available_copies INT NOT NULL DEFAULT 1 CHECK (available_copies >= 0),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_books_author FOREIGN KEY (author_id) REFERENCES authors(author_id) ON DELETE RESTRICT,
    CONSTRAINT fk_books_category FOREIGN KEY (category_id) REFERENCES categories(category_id) ON DELETE RESTRICT,
    CONSTRAINT fk_books_publisher FOREIGN KEY (publisher_id) REFERENCES publishers(publisher_id) ON DELETE RESTRICT,
    CONSTRAINT chk_copies CHECK (available_copies <= total_copies)
);

CREATE TABLE IF NOT EXISTS borrowers (
    borrower_id INT AUTO_INCREMENT PRIMARY KEY,
    student_id VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    status VARCHAR(20) DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'SUSPENDED', 'GRADUATED')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS borrow_records (
    record_id INT AUTO_INCREMENT PRIMARY KEY,
    borrower_id INT NOT NULL,
    book_id INT NOT NULL,
    borrowed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    due_date TIMESTAMP NOT NULL,
    returned_at TIMESTAMP NULL,
    status VARCHAR(20) DEFAULT 'BORROWED' CHECK (status IN ('BORROWED', 'RETURNED', 'OVERDUE', 'LOST')),
    fine_amount DECIMAL(8, 2) DEFAULT 0.00 CHECK (fine_amount >= 0),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_borrow_borrower FOREIGN KEY (borrower_id) REFERENCES borrowers(borrower_id) ON DELETE RESTRICT,
    CONSTRAINT fk_borrow_book FOREIGN KEY (book_id) REFERENCES books(book_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS fine_payments (
    payment_id INT AUTO_INCREMENT PRIMARY KEY,
    record_id INT NOT NULL,
    amount DECIMAL(8, 2) NOT NULL CHECK (amount > 0),
    paid_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    payment_method VARCHAR(50) DEFAULT 'CASH',
    CONSTRAINT fk_fine_record FOREIGN KEY (record_id) REFERENCES borrow_records(record_id) ON DELETE RESTRICT
);

-- Indexes for performance optimization
CREATE INDEX idx_books_isbn ON books(isbn);
CREATE INDEX idx_books_title ON books(title);
CREATE INDEX idx_books_author_cat ON books(author_id, category_id);
CREATE INDEX idx_borrowers_student_id ON borrowers(student_id);
CREATE INDEX idx_borrow_records_due_status ON borrow_records(due_date, status);
CREATE INDEX idx_borrow_records_borrower_id ON borrow_records(borrower_id);
CREATE INDEX idx_borrow_records_book_id ON borrow_records(book_id);

-- ============================================================================
-- 4. GOLD LAYER VIEWS
-- ============================================================================

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
    GREATEST(0, TIMESTAMPDIFF(DAY, br.due_date, COALESCE(br.returned_at, NOW()))) AS days_overdue,
    (GREATEST(0, TIMESTAMPDIFF(DAY, br.due_date, COALESCE(br.returned_at, NOW()))) * 5.00) AS calculated_fine
FROM borrow_records br
JOIN borrowers bw ON br.borrower_id = bw.borrower_id
JOIN books bk ON br.book_id = bk.book_id
WHERE br.due_date < NOW() AND br.status IN ('BORROWED', 'OVERDUE');

-- ============================================================================
-- 5. STORED PROCEDURES (MySQL 8.0)
-- ============================================================================

DELIMITER //

CREATE PROCEDURE sp_issue_book(
    IN p_student_id VARCHAR(50),
    IN p_borrower_name VARCHAR(255),
    IN p_book_title VARCHAR(255),
    IN p_loan_days INT,
    OUT p_success BOOLEAN,
    OUT p_message VARCHAR(255),
    OUT p_record_id INT,
    OUT p_due_date DATETIME
)
BEGIN
    DECLARE v_borrower_id INT;
    DECLARE v_book_id INT;
    DECLARE v_avail_copies INT;

    START TRANSACTION;

    INSERT INTO borrowers (student_id, name)
    VALUES (p_student_id, p_borrower_name)
    ON DUPLICATE KEY UPDATE name = VALUES(name);
    
    SELECT borrower_id INTO v_borrower_id FROM borrowers WHERE student_id = p_student_id;

    SELECT book_id, available_copies INTO v_book_id, v_avail_copies
    FROM books
    WHERE LOWER(title) = LOWER(p_book_title) OR isbn = p_book_title
    ORDER BY available_copies DESC LIMIT 1
    FOR UPDATE;

    IF v_book_id IS NULL THEN
        SET p_success = FALSE;
        SET p_message = 'Book not found in inventory.';
        SET p_record_id = NULL;
        SET p_due_date = NULL;
        ROLLBACK;
    ELSEIF v_avail_copies <= 0 THEN
        SET p_success = FALSE;
        SET p_message = 'Book is currently out of stock.';
        SET p_record_id = NULL;
        SET p_due_date = NULL;
        ROLLBACK;
    ELSE
        UPDATE books SET available_copies = available_copies - 1 WHERE book_id = v_book_id;
        SET p_due_date = DATE_ADD(NOW(), INTERVAL IFNULL(p_loan_days, 7) DAY);

        INSERT INTO borrow_records (borrower_id, book_id, due_date, status)
        VALUES (v_borrower_id, v_book_id, p_due_date, 'BORROWED');
        
        SET p_record_id = LAST_INSERT_ID();
        SET p_success = TRUE;
        SET p_message = 'Book issued successfully.';
        COMMIT;
    END IF;
END //

CREATE PROCEDURE sp_return_book(
    IN p_record_id INT,
    OUT p_success BOOLEAN,
    OUT p_message VARCHAR(255),
    OUT p_returned_at DATETIME,
    OUT p_fine DECIMAL(8, 2)
)
BEGIN
    DECLARE v_book_id INT;
    DECLARE v_due_date DATETIME;
    DECLARE v_status VARCHAR(20);
    DECLARE v_days_overdue INT;

    START TRANSACTION;

    SELECT book_id, due_date, status INTO v_book_id, v_due_date, v_status
    FROM borrow_records
    WHERE record_id = p_record_id
    FOR UPDATE;

    IF v_book_id IS NULL THEN
        SET p_success = FALSE;
        SET p_message = 'Borrow record not found.';
        SET p_returned_at = NULL;
        SET p_fine = 0.00;
        ROLLBACK;
    ELSEIF v_status = 'RETURNED' THEN
        SET p_success = FALSE;
        SET p_message = 'Book has already been returned.';
        SET p_returned_at = NULL;
        SET p_fine = 0.00;
        ROLLBACK;
    ELSE
        SET p_returned_at = NOW();
        SET p_fine = 0.00;
        IF p_returned_at > v_due_date THEN
            SET v_days_overdue = TIMESTAMPDIFF(DAY, v_due_date, p_returned_at);
            SET p_fine = v_days_overdue * 5.00;
        END IF;

        UPDATE borrow_records 
        SET returned_at = p_returned_at, status = 'RETURNED', fine_amount = p_fine
        WHERE record_id = p_record_id;

        UPDATE books SET available_copies = available_copies + 1 WHERE book_id = v_book_id;

        SET p_success = TRUE;
        SET p_message = 'Book returned successfully.';
        COMMIT;
    END IF;
END //

DELIMITER ;
