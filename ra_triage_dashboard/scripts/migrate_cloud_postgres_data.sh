#!/usr/bin/env bash
set -euo pipefail

CLUSTER_VERSION="${DASHBOARD_POSTGRES_VERSION:-14}"
CLUSTER_NAME="${DASHBOARD_POSTGRES_CLUSTER:-main}"
DATABASE_NAME="${DASHBOARD_POSTGRES_DATABASE:-ra_triage_dashboard}"
SOURCE_DATA_DIR="${DASHBOARD_POSTGRES_SOURCE_DATA_DIR:-/var/lib/postgresql/$CLUSTER_VERSION/$CLUSTER_NAME}"
TARGET_DATA_DIR="${DASHBOARD_POSTGRES_DATA_DIR:-/volume/postgresql/$CLUSTER_VERSION/$CLUSTER_NAME}"
APP_PORT="${DASHBOARD_PORT:-8785}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ ! "$CLUSTER_VERSION" =~ ^[0-9]+$ ]] || [[ ! "$CLUSTER_NAME" =~ ^[a-z0-9_-]+$ ]]; then
  echo "Invalid PostgreSQL cluster identity" >&2
  exit 1
fi
if [[ ! "$DATABASE_NAME" =~ ^[a-z_][a-z0-9_]{0,62}$ ]]; then
  echo "Invalid PostgreSQL database name: $DATABASE_NAME" >&2
  exit 1
fi
case "$TARGET_DATA_DIR" in
  /volume/*) ;;
  *)
    echo "Refusing a production PostgreSQL data directory outside /volume" >&2
    exit 1
    ;;
esac
if ss -H -ltn "sport = :$APP_PORT" | grep -q .; then
  echo "Dashboard port $APP_PORT is still listening; stop application writes first" >&2
  exit 1
fi
if [[ ! -f "$SOURCE_DATA_DIR/PG_VERSION" ]]; then
  echo "Source PostgreSQL cluster is missing: $SOURCE_DATA_DIR" >&2
  exit 1
fi
if [[ "$(findmnt -n -o FSTYPE -T /volume)" == "overlay" ]]; then
  echo "Target PostgreSQL data directory would still be on overlay" >&2
  exit 1
fi

configured_data_dir="$(sudo pg_conftool "$CLUSTER_VERSION" "$CLUSTER_NAME" show data_directory | tr -d "'\"" | xargs)"
if [[ "$configured_data_dir" == "$TARGET_DATA_DIR" ]]; then
  [[ -f "$TARGET_DATA_DIR/PG_VERSION" ]] || {
    echo "Cluster config points at a missing persistent data directory" >&2
    exit 1
  }
  pg_isready --dbname "$DATABASE_NAME"
  echo "PostgreSQL already uses persistent data directory: $TARGET_DATA_DIR"
  exit 0
fi
if [[ "$configured_data_dir" != "$SOURCE_DATA_DIR" ]]; then
  echo "Configured data directory is neither expected source nor target: $configured_data_dir" >&2
  exit 1
fi
if [[ -e "$TARGET_DATA_DIR" ]] && [[ -n "$(sudo find "$TARGET_DATA_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  echo "Target data directory is not empty: $TARGET_DATA_DIR" >&2
  exit 1
fi

echo "Creating a verified logical backup before the physical move..."
"$SCRIPT_DIR/backup_cloud_postgres.sh" >/dev/null

before_counts="$(mktemp)"
after_counts="$(mktemp)"
cleanup() {
  rm -f -- "$before_counts" "$after_counts"
}
trap cleanup EXIT

table_counts() {
  sudo -u postgres psql --dbname "$DATABASE_NAME" --tuples-only --no-align \
    --command "SELECT format('SELECT %L || chr(9) || count(*) FROM %I.%I;', schemaname || '.' || tablename, schemaname, tablename) FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename" \
    | sudo -u postgres psql --dbname "$DATABASE_NAME" --tuples-only --no-align
}

table_counts > "$before_counts"
sudo pg_ctlcluster "$CLUSTER_VERSION" "$CLUSTER_NAME" stop

rollback_required=1
rollback() {
  status=$?
  trap - ERR INT TERM
  if (( rollback_required )); then
    echo "Migration failed; restoring cluster configuration to $SOURCE_DATA_DIR" >&2
    sudo pg_ctlcluster "$CLUSTER_VERSION" "$CLUSTER_NAME" stop >/dev/null 2>&1 || true
    sudo pg_conftool "$CLUSTER_VERSION" "$CLUSTER_NAME" set data_directory "$SOURCE_DATA_DIR" || true
    sudo pg_ctlcluster "$CLUSTER_VERSION" "$CLUSTER_NAME" start || true
  fi
  exit "$status"
}
trap rollback ERR INT TERM

sudo install -d -m 700 -o postgres -g postgres "$TARGET_DATA_DIR"
sudo rsync -aHAX --numeric-ids "$SOURCE_DATA_DIR/" "$TARGET_DATA_DIR/"
sudo pg_conftool "$CLUSTER_VERSION" "$CLUSTER_NAME" set data_directory "$TARGET_DATA_DIR"
sudo pg_ctlcluster "$CLUSTER_VERSION" "$CLUSTER_NAME" start
pg_isready --dbname "$DATABASE_NAME"

active_data_dir="$(sudo -u postgres psql --dbname postgres --tuples-only --no-align --command 'SHOW data_directory')"
if [[ "$active_data_dir" != "$TARGET_DATA_DIR" ]]; then
  echo "PostgreSQL started from unexpected data directory: $active_data_dir" >&2
  false
fi
table_counts > "$after_counts"
diff -u "$before_counts" "$after_counts"

rollback_required=0
trap - ERR INT TERM
echo "PostgreSQL data directory migrated and verified: $TARGET_DATA_DIR"
echo "The old physical directory remains intact for rollback: $SOURCE_DATA_DIR"
