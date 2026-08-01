#!/usr/bin/env bash
set -euo pipefail

SERVICE_USER="${DASHBOARD_POSTGRES_SERVICE_USER:-$(id -un)}"
DATABASE_NAME="${DASHBOARD_POSTGRES_DATABASE:-ra_triage_dashboard}"
DATA_DIR="${DASHBOARD_DATA_DIR:-/volume/home/workspace/ra_triage_dashboard_data}"
URL_FILE="${DASHBOARD_DATABASE_URL_FILE:-$DATA_DIR/postgres_url.pending}"
VENV_DIR="${DASHBOARD_VENV_DIR:-/volume/home/workspace/ra_triage_dashboard_venv}"

if [[ ! "$SERVICE_USER" =~ ^[a-z_][a-z0-9_-]{0,62}$ ]]; then
  echo "Invalid PostgreSQL service user: $SERVICE_USER" >&2
  exit 1
fi
if [[ ! "$DATABASE_NAME" =~ ^[a-z_][a-z0-9_]{0,62}$ ]]; then
  echo "Invalid PostgreSQL database name: $DATABASE_NAME" >&2
  exit 1
fi

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y postgresql-14 postgresql-client-14
if ! pg_isready --quiet; then
  if ! sudo systemctl enable --now postgresql 2>/dev/null; then
    # cloud_server currently runs without systemd as PID 1. pg_ctlcluster starts
    # the distro-managed cluster directly while preserving the same config/data.
    sudo pg_ctlcluster 14 main start
  fi
fi

if ! sudo -u postgres psql --dbname postgres --tuples-only --no-align \
  --command "SELECT 1 FROM pg_roles WHERE rolname = '$SERVICE_USER'" | grep -qx 1; then
  sudo -u postgres createuser --login "$SERVICE_USER"
fi
if ! sudo -u postgres psql --dbname postgres --tuples-only --no-align \
  --command "SELECT 1 FROM pg_database WHERE datname = '$DATABASE_NAME'" | grep -qx 1; then
  sudo -u postgres createdb --owner "$SERVICE_USER" "$DATABASE_NAME"
fi

install -d -m 700 -o "$SERVICE_USER" -g "$(id -gn "$SERVICE_USER")" "$DATA_DIR"
URL_VALUE="postgresql:///$DATABASE_NAME?host=/var/run/postgresql"
umask 077
printf '%s\n' "$URL_VALUE" > "$URL_FILE"
chown "$SERVICE_USER:$(id -gn "$SERVICE_USER")" "$URL_FILE"
chmod 600 "$URL_FILE"

"$VENV_DIR/bin/python3" -c \
  'import pathlib,psycopg,sys; url=pathlib.Path(sys.argv[1]).read_text().strip(); conn=psycopg.connect(url); print(conn.execute("SELECT current_database(), current_user").fetchone()); conn.close()' \
  "$URL_FILE"

pg_isready --dbname "$DATABASE_NAME"
echo "PostgreSQL is ready. Migrate with $URL_FILE, then atomically promote it to $DATA_DIR/postgres_url."
