#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_SCRIPT="$APP_ROOT/scripts/backup_cloud_postgres.sh"
CRON_LOG="${DASHBOARD_POSTGRES_BACKUP_LOG:-/volume/home/workspace/ra_triage_dashboard_data/postgres_backups/cron.log}"
CRON_SCHEDULE="${DASHBOARD_POSTGRES_BACKUP_SCHEDULE:-15 2 * * *}"
BACKUP_DIR="$(dirname "$CRON_LOG")"
SCHEDULE_STATE="$BACKUP_DIR/.backup-schedule"
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
read -r -a schedule_fields <<< "$CRON_SCHEDULE"
schedule_pattern='^[0-9*/, -]+$'
if (( ${#schedule_fields[@]} != 5 )) || [[ ! "$CRON_SCHEDULE" =~ $schedule_pattern ]]; then
  echo "Invalid PostgreSQL backup cron schedule: $CRON_SCHEDULE" >&2
  exit 1
fi

install -d -m 700 "$BACKUP_DIR"
current="$(mktemp)"
updated="$(mktemp)"
schedule_state_tmp=""
cleanup() {
  rm -f -- "$current" "$updated"
  [[ -z "$schedule_state_tmp" ]] || rm -f -- "$schedule_state_tmp"
}
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
umask 077
schedule_state_tmp="$(mktemp "$BACKUP_DIR/.backup-schedule.XXXXXX")"
printf 'schedule=%s\ninstalled_at=%s\n' \
  "$CRON_SCHEDULE" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$schedule_state_tmp"
mv -- "$schedule_state_tmp" "$SCHEDULE_STATE"
echo "Installed PostgreSQL backup schedule: $CRON_SCHEDULE"
