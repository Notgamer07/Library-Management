-- ============================================================================
-- Gold Layer Analytics & Reporting Database Schema (PostgreSQL 16)
-- Dedicated Instance for High-Speed Analytical Queries, KPIs & Business Intelligence
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ----------------------------------------------------------------------------
-- 1. Day-wise Book Views Aggregation
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold_book_views_daily (
    summary_date DATE NOT NULL,
    book_id INT NOT NULL,
    book_title VARCHAR(255) NOT NULL,
    category_name VARCHAR(100) DEFAULT 'General',
    total_views INT NOT NULL DEFAULT 0,
    unique_users INT NOT NULL DEFAULT 0,
    last_updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (summary_date, book_id)
);

CREATE INDEX IF NOT EXISTS idx_gold_views_daily_date ON gold_book_views_daily(summary_date);
CREATE INDEX IF NOT EXISTS idx_gold_views_daily_book ON gold_book_views_daily(book_id);

-- ----------------------------------------------------------------------------
-- 2. Month-wise Book Views Aggregation
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold_book_views_monthly (
    summary_year INT NOT NULL,
    summary_month INT NOT NULL,
    book_id INT NOT NULL,
    book_title VARCHAR(255) NOT NULL,
    category_name VARCHAR(100) DEFAULT 'General',
    total_views INT NOT NULL DEFAULT 0,
    unique_users INT NOT NULL DEFAULT 0,
    last_updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (summary_year, summary_month, book_id)
);

CREATE INDEX IF NOT EXISTS idx_gold_views_monthly_period ON gold_book_views_monthly(summary_year, summary_month);
CREATE INDEX IF NOT EXISTS idx_gold_views_monthly_book ON gold_book_views_monthly(book_id);

-- ----------------------------------------------------------------------------
-- 3. Day-wise Book Loans & Returns Aggregation
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold_loans_returns_daily (
    summary_date DATE PRIMARY KEY,
    total_loans INT NOT NULL DEFAULT 0,
    total_returns INT NOT NULL DEFAULT 0,
    total_overdue INT NOT NULL DEFAULT 0,
    total_fines_accrued NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    total_fines_collected NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    last_updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- 4. Month-wise Book Loans & Returns Aggregation
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold_loans_returns_monthly (
    summary_year INT NOT NULL,
    summary_month INT NOT NULL,
    total_loans INT NOT NULL DEFAULT 0,
    total_returns INT NOT NULL DEFAULT 0,
    total_overdue INT NOT NULL DEFAULT 0,
    total_fines_accrued NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    total_fines_collected NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    last_updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (summary_year, summary_month)
);
