#!/usr/bin/env bash
set -euo pipefail

DATABASE_NAME="${DASHBOARD_POSTGRES_DATABASE:-ra_triage_dashboard}"
DATA_DIR="${DASHBOARD_DATA_DIR:-/volume/home/workspace/ra_triage_dashboard_data}"
BACKUP_DIR="${DASHBOARD_POSTGRES_BACKUP_DIR:-$DATA_DIR/postgres_backups}"
RETENTION_COUNT="${DASHBOARD_POSTGRES_BACKUP_RETENTION:-14}"

if [[ ! "$DATABASE_NAME" =~ ^[a-z_][a-z0-9_]{0,62}$ ]]; then
  echo "Invalid PostgreSQL database name: $DATABASE_NAME" >&2
  exit 1
fi
if [[ ! "$RETENTION_COUNT" =~ ^[1-9][0-9]*$ ]]; then
  echo "DASHBOARD_POSTGRES_BACKUP_RETENTION must be a positive integer" >&2
  exit 1
fi
case "$BACKUP_DIR" in
  /volume/*) ;;
  *)
    echo "Refusing to store production backups outside /volume: $BACKUP_DIR" >&2
    exit 1
    ;;
esac

install -d -m 700 "$BACKUP_DIR"
if [[ "$(findmnt -n -o FSTYPE -T "$BACKUP_DIR")" == "overlay" ]]; then
  echo "Refusing to store PostgreSQL backups on an overlay filesystem" >&2
  exit 1
fi

umask 077
exec 9>"$BACKUP_DIR/.backup.lock"
if ! flock -n 9; then
  echo "Another PostgreSQL backup is already running" >&2
  exit 0
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
final_dump="$BACKUP_DIR/${DATABASE_NAME}-${timestamp}.dump"
final_checksum="${final_dump}.sha256"
temporary_dump="$(mktemp "$BACKUP_DIR/.${DATABASE_NAME}-${timestamp}.XXXXXX.dump")"
temporary_checksum="${temporary_dump}.sha256"

cleanup() {
  rm -f -- "$temporary_dump" "$temporary_checksum"
}
trap cleanup EXIT

pg_dump \
  --dbname "$DATABASE_NAME" \
  --format custom \
  --compress 6 \
  --no-owner \
  --no-privileges \
  --file "$temporary_dump"
pg_restore --list "$temporary_dump" >/dev/null
(
  cd "$BACKUP_DIR"
  sha256sum "$(basename "$temporary_dump")" > "$(basename "$temporary_checksum")"
)

mv -- "$temporary_dump" "$final_dump"
sed "s/$(basename "$temporary_dump")/$(basename "$final_dump")/" \
  "$temporary_checksum" > "$final_checksum"
rm -f -- "$temporary_checksum"
trap - EXIT

mapfile -t backups < <(
  find "$BACKUP_DIR" -maxdepth 1 -type f \
    -name "${DATABASE_NAME}-????????T??????Z.dump" -print | sort -r
)
if (( ${#backups[@]} > RETENTION_COUNT )); then
  for old_dump in "${backups[@]:RETENTION_COUNT}"; do
    rm -f -- "$old_dump" "${old_dump}.sha256"
  done
fi

echo "$final_dump"
