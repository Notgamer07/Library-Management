#!/usr/bin/env bash
# ============================================================================
# PostgreSQL 16 Database Restore Script
# Restores compressed .sql.gz dump files onto PostgreSQL 16 target instance
# ============================================================================

set -e

if [ -z "$1" ]; then
    echo "Usage: ./scripts/restore.sh <path-to-backup-file.sql.gz>"
    echo "Example: ./scripts/restore.sh ./backups/library_db_backup_20260809_010000.sql.gz"
    exit 1
fi

BACKUP_FILE="$1"
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DB:-library_db}"

if [ ! -f "${BACKUP_FILE}" ]; then
    echo "[ERROR] Specified backup file '${BACKUP_FILE}' does not exist."
    exit 1
fi

echo "======================================================================"
echo "[$(date)] Restoring PostgreSQL 16 Backup from: ${BACKUP_FILE}"
echo "Target DB: ${DB_NAME} (${DB_HOST}:${DB_PORT})"
echo "======================================================================"

# Terminate existing database connections before drop/recreate
PGPASSWORD="${POSTGRES_PASSWORD:-postgres}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -c "
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${DB_NAME}' AND pid <> pg_backend_pid();
" || true

# Restore dump
gunzip -c "${BACKUP_FILE}" | PGPASSWORD="${POSTGRES_PASSWORD:-postgres}" psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}"

echo "[SUCCESS] Database restoration complete!"
