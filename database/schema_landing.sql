-- ============================================================================
-- Landing Site Database Schema (PostgreSQL 16)
-- Dedicated Instance for High-Speed Asynchronous Ingestion & Writes
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Raw Books Ingest Staging Table
CREATE TABLE IF NOT EXISTS landing_books_ingest (
    ingest_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    raw_payload JSONB NOT NULL,
    source_channel VARCHAR(50) DEFAULT 'API',
    received_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    processed_flag BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_landing_books_processed ON landing_books_ingest(processed_flag);

-- 2. Raw Borrow / Loan Ingest Staging Table
CREATE TABLE IF NOT EXISTS landing_borrow_ingest (
    ingest_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    raw_payload JSONB NOT NULL,
    source_channel VARCHAR(50) DEFAULT 'API',
    received_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    processed_flag BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_landing_borrow_processed ON landing_borrow_ingest(processed_flag);
