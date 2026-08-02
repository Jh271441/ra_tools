#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_SCRIPT="$APP_ROOT/scripts/backup_cloud_postgres.sh"
CRON_LOG="${DASHBOARD_POSTGRES_BACKUP_LOG:-/volume/home/workspace/ra_triage_dashboard_data/postgres_backups/cron.log}"
CRON_SCHEDULE="${DASHBOARD_POSTGRES_BACKUP_SCHEDULE:-15 2 * * *}"
MARKER_BEGIN="# BEGIN RA_TRIAGE_POSTGRES_BACKUP"
MARKER_END="# END RA_TRIAGE_POSTGRES_BACKUP"

[[ -x "$BACKUP_SCRIPT" ]] || {
  echo "Backup script is missing or not executable: $BACKUP_SCRIPT" >&2
  exit 1
}
case "$CRON_LOG" in
  /volume/*) ;;
  *) echo "Refusing a cron log outside /volume: $CRON_LOG" >&2; exit 1 ;;
esac

install -d -m 700 "$(dirname "$CRON_LOG")"
current="$(mktemp)"
updated="$(mktemp)"
cleanup() { rm -f -- "$current" "$updated"; }
trap cleanup EXIT
crontab -l > "$current" 2>/dev/null || true
sed "/^${MARKER_BEGIN}$/,/^${MARKER_END}$/d" "$current" > "$updated"
{
  echo "$MARKER_BEGIN"
  printf '%s %q >> %q 2>&1\n' "$CRON_SCHEDULE" "$BACKUP_SCRIPT" "$CRON_LOG"
  echo "$MARKER_END"
} >> "$updated"
crontab "$updated"

if ! pgrep -x cron >/dev/null; then
  sudo cron
fi
pgrep -x cron >/dev/null || {
  echo "cron daemon did not start" >&2
  exit 1
}
echo "Installed PostgreSQL backup schedule: $CRON_SCHEDULE"
