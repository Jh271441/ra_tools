#!/usr/bin/env bash
set -euo pipefail

DATABASE_NAME="${DASHBOARD_POSTGRES_DATABASE:-ra_triage_dashboard}"
DATA_DIR="${DASHBOARD_DATA_DIR:-/volume/home/workspace/ra_triage_dashboard_data}"
BACKUP_DIR="${DASHBOARD_POSTGRES_BACKUP_DIR:-$DATA_DIR/postgres_backups}"
BACKUP_FILE="${1:-}"

if [[ ! "$DATABASE_NAME" =~ ^[a-z_][a-z0-9_]{0,62}$ ]]; then
  echo "Invalid PostgreSQL database name: $DATABASE_NAME" >&2
  exit 1
fi
if [[ -z "$BACKUP_FILE" ]]; then
  BACKUP_FILE="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name "${DATABASE_NAME}-????????T??????Z.dump" -print | sort -r | head -1)"
fi
case "$BACKUP_FILE" in
  "$BACKUP_DIR"/*.dump) ;;
  *) echo "Backup must be a dump inside $BACKUP_DIR" >&2; exit 1 ;;
esac
[[ -f "$BACKUP_FILE" && -f "${BACKUP_FILE}.sha256" ]] || {
  echo "Backup or checksum is missing: $BACKUP_FILE" >&2
  exit 1
}

(
  cd "$BACKUP_DIR"
  sha256sum --check "$(basename "${BACKUP_FILE}.sha256")"
)
pg_restore --list "$BACKUP_FILE" >/dev/null

RESTORE_DATABASE="ra_triage_restore_$(date -u +%Y%m%d%H%M%S)_$$"
if [[ ! "$RESTORE_DATABASE" =~ ^[a-z0-9_]+$ ]]; then
  echo "Generated invalid restore database name" >&2
  exit 1
fi
cleanup() {
  sudo -u postgres dropdb --if-exists --force "$RESTORE_DATABASE" >/dev/null 2>&1 || true
}
trap cleanup EXIT

sudo -u postgres createdb --template template0 "$RESTORE_DATABASE"
sudo -u postgres pg_restore \
  --dbname "$RESTORE_DATABASE" \
  --no-owner \
  --no-privileges \
  --exit-on-error \
  "$BACKUP_FILE"

table_counts() {
  local database="$1"
  sudo -u postgres psql --dbname "$database" --tuples-only --no-align \
    --command "SELECT format('SELECT %L || chr(9) || count(*) FROM %I.%I;', schemaname || '.' || tablename, schemaname, tablename) FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename" \
    | sudo -u postgres psql --dbname "$database" --tuples-only --no-align
}

source_counts="$(mktemp)"
restored_counts="$(mktemp)"
cleanup_files() { rm -f -- "$source_counts" "$restored_counts"; }
trap 'cleanup_files; cleanup' EXIT
table_counts "$DATABASE_NAME" > "$source_counts"
table_counts "$RESTORE_DATABASE" > "$restored_counts"
diff -u "$source_counts" "$restored_counts"

echo "Backup restore verified against live table counts: $BACKUP_FILE"
