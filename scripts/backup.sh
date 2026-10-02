#!/usr/bin/env bash
# ============================================================================
# PostgreSQL 16 Zero-Downtime Backup Automation Script
# Generates timestamped gzip compressed database dumps with 7-day retention
# ============================================================================

set -e

BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DB_HOST="${SILVER_DB_HOST:-${POSTGRES_HOST:-localhost}}"
DB_PORT="${SILVER_DB_PORT:-${POSTGRES_PORT:-5432}}"
DB_USER="${SILVER_DB_USER:-${POSTGRES_USER:-postgres}}"
DB_NAME="${SILVER_DB_NAME:-${POSTGRES_DB:-silver_db}}"
BACKUP_FILE="${BACKUP_DIR}/library_db_backup_${TIMESTAMP}.sql.gz"

mkdir -p "${BACKUP_DIR}"

echo "======================================================================"
echo "[$(date)] Starting PostgreSQL 16 Backup for '${DB_NAME}'..."
echo "======================================================================"

if [ -z "${POSTGRES_PASSWORD}" ] && [ -z "${SILVER_DB_PASSWORD}" ]; then
    echo "[ERROR] POSTGRES_PASSWORD or SILVER_DB_PASSWORD environment variable is required."
    exit 1
fi
BACKUP_PASSWORD="${SILVER_DB_PASSWORD:-${POSTGRES_PASSWORD}}"

# Execute pg_dump with gzip compression
PGPASSWORD="${BACKUP_PASSWORD}" pg_dump -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -F p -d "${DB_NAME}" | gzip > "${BACKUP_FILE}"

if [ -f "${BACKUP_FILE}" ]; then
    FILE_SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
    echo "[SUCCESS] Backup created successfully: ${BACKUP_FILE} (${FILE_SIZE})"
else
    echo "[ERROR] Backup file creation failed!"
    exit 1
fi

# Clean up backups older than 7 days
echo "Pruning backup files older than 7 days..."
find "${BACKUP_DIR}" -type f -name "library_db_backup_*.sql.gz" -mtime +7 -delete

echo "Backup complete!"
