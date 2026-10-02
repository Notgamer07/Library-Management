-- ============================================================================
-- Bronze Layer Database Schema (PostgreSQL 16)
-- Dedicated Instance for Raw Ingestion, Stream Staging & Dead-Letter Audit Errors
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ----------------------------------------------------------------------------
-- 1. Raw Books Ingest Staging Table
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze_books_ingest (
    ingest_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    raw_payload JSONB NOT NULL,
    source_channel VARCHAR(50) DEFAULT 'API',
    received_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    processed_flag BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_bronze_books_processed ON bronze_books_ingest(processed_flag);

-- ----------------------------------------------------------------------------
-- 2. Raw Borrow / Loan Ingest Staging Table
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze_borrow_ingest (
    ingest_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    raw_payload JSONB NOT NULL,
    source_channel VARCHAR(50) DEFAULT 'API',
    received_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    processed_flag BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_bronze_borrow_processed ON bronze_borrow_ingest(processed_flag);

-- ----------------------------------------------------------------------------
-- 3. Raw Book Views Ingest Staging Table
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze_book_views_ingest (
    view_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    raw_payload JSONB NOT NULL,
    source_channel VARCHAR(50) DEFAULT 'API',
    received_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    processed_flag BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_bronze_views_processed ON bronze_book_views_ingest(processed_flag);

-- ----------------------------------------------------------------------------
-- 4. Bronze Ingestion Errors (Dead Letter Queue / Audit Log)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze_ingestion_errors (
    error_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_layer VARCHAR(20) DEFAULT 'BRONZE',
    source_stream VARCHAR(50) NOT NULL, -- 'BOOKS', 'BORROW', 'BOOK_VIEWS'
    raw_data JSONB,
    error_message TEXT NOT NULL,
    logged_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_bronze_errors_stream ON bronze_ingestion_errors(source_stream);
