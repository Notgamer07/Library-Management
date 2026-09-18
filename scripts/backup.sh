#!/usr/bin/env bash
# ============================================================================
# PostgreSQL 16 Zero-Downtime Backup Automation Script
# Generates timestamped gzip compressed database dumps with 7-day retention
# ============================================================================

set -e

BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DB:-library_db}"
BACKUP_FILE="${BACKUP_DIR}/library_db_backup_${TIMESTAMP}.sql.gz"

mkdir -p "${BACKUP_DIR}"

echo "======================================================================"
echo "[$(date)] Starting PostgreSQL 16 Backup for '${DB_NAME}'..."
echo "======================================================================"

# Execute pg_dump with gzip compression
PGPASSWORD="${POSTGRES_PASSWORD:-postgres}" pg_dump -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -F p -d "${DB_NAME}" | gzip > "${BACKUP_FILE}"

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
