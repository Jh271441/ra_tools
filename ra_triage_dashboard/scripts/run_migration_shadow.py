#!/usr/bin/env python3
"""Run an isolated, loopback-only migration preview with external writers off.

The config must point at its own restored database and state directory. This
launcher refuses snapshots with queued/running work and rejects every mutating
HTTP request, including requests bearing otherwise valid identity headers.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

DISABLED = (
    'DASHBOARD_SYNC_TRAIL_ON_START', 'DASHBOARD_GT_SYNC_ENABLED',
    'DASHBOARD_TRAIL_ATTRIBUTE_WRITE_ENABLED',
    'DASHBOARD_TRAIL_ATTRIBUTE_REVIEW_WRITE_ENABLED', 'DASHBOARD_TRAIL_WRITE_ENABLED',
    'DASHBOARD_BATCH_PREDICTION_ENABLED', 'DASHBOARD_AUTOTRIAGE_PUSH_ENABLED',
    'DASHBOARD_DCHAT_NOTIFICATIONS_ENABLED', 'DASHBOARD_TRAIL_DETAIL_METADATA_ENABLED',
    'DASHBOARD_SMOKE_LOOPBACK_ADMIN_ENABLED',
    'DASHBOARD_KYLIN_SSO_ENABLED', 'DASHBOARD_SEED_EXAMPLES_ENABLED',
)


def validate_config(env, sso_preview=False):
    if env.get('DASHBOARD_DEPLOYMENT_MODE') != 'production':
        raise ValueError('Shadow must retain production identity restrictions')
    if sso_preview:
        if env.get('DASHBOARD_TRUST_PROXY_IDENTITY_HEADERS') != 'false':
            raise ValueError('SSO preview must validate Kylin tickets, not synthetic proxy headers')
        if not str(env.get('DASHBOARD_KYLIN_SSO_APP_ID', '')).isdigit():
            raise ValueError('SSO preview requires an explicit gateway-matching App ID')
    elif env.get('DASHBOARD_TRUST_PROXY_IDENTITY_HEADERS') != 'true' or not env.get('DASHBOARD_TRUSTED_INGRESS_TOKEN_FILE'):
        raise ValueError('Shadow requires its own private ingress token file')
    for key in DISABLED:
        if key == 'DASHBOARD_KYLIN_SSO_ENABLED' and sso_preview:
            if env.get(key) != 'true' or env.get('DASHBOARD_BASE_PATH') != '/manual-migration':
                raise ValueError('SSO preview requires its dedicated path and server ticket validation')
            continue
        if env.get(key) != 'false':
            raise ValueError(f'Shadow requires {key}=false')


def validate_media_mounts(mount_table=Path('/proc/mounts'), sentinel=Path('/mnt/ofs/manual-ro/.manual-volume.json')):
    rows = [line.split() for line in mount_table.read_text().splitlines()]
    for path in ('/mnt/ofs/manual-ro', '/mnt/ofs/manual-bags-ro'):
        if not any(len(row) >= 4 and row[0] == 'orangefs:remote-assist-stuck-model'
                   and row[1] == path and 'ro' in row[3].split(',') for row in rows):
            raise ValueError('Expected read-only Manual OFS mounts before application startup')
    if json.loads(sentinel.read_text()).get('service') != 'manual':
        raise ValueError('Unexpected Manual OFS sentinel')


class RejectWrites:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and scope.get('method') not in {'GET', 'HEAD', 'OPTIONS'}:
            from starlette.responses import JSONResponse
            response = JSONResponse({'detail': 'Migration shadow is read-only.'}, status_code=503)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--app-root', type=Path, required=True)
    parser.add_argument('--pgdata', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18785)
    parser.add_argument('--sso-preview', action='store_true', help='Read-only ingress acceptance on /manual-migration')
    args = parser.parse_args()
    env = json.loads(args.config.read_text())
    validate_config(env, args.sso_preview)
    if args.sso_preview and args.port != 18786:
        raise ValueError('SSO preview must use its dedicated 18786 port')
    validate_media_mounts()
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    url = Path(env['DASHBOARD_DATABASE_URL_FILE']).read_text().strip()
    ci = conninfo_to_dict(url)
    if not ci.get('dbname', '').startswith('manual_shadow_'):
        raise ValueError('Refusing a non-shadow database')
    if not ci.get('host', '').startswith('/local-data/services/manual/') or ci.get('password'):
        raise ValueError('Expected private target Unix socket with peer authentication')
    with psycopg.connect(**{**ci, 'user': 'didi'}) as admin:
        actual = Path(admin.execute('SHOW data_directory').fetchone()[0]).resolve()
    if actual != args.pgdata.resolve():
        raise ValueError('PostgreSQL data directory differs from the pinned target')
    fs = subprocess.check_output(['findmnt', '-n', '-o', 'FSTYPE', '-T', str(actual)], text=True).strip()
    if fs in {'overlay', 'tmpfs', 'fuse.ofs'} or not fs:
        raise ValueError('PostgreSQL must use local persistent storage')
    with psycopg.connect(url) as conn:
        conn.execute('BEGIN READ ONLY')
        pending = conn.execute("SELECT count(*) FROM batch_prediction_jobs WHERE status IN ('queued','running') OR publish_status IN ('queued','running')").fetchone()[0]
        pending += conn.execute("SELECT count(*) FROM inference_jobs WHERE status IN ('queued','running')").fetchone()[0]
        if pending:
            raise ValueError('Snapshot contains active jobs; isolate them before startup')
    os.environ.update(env)
    # This reflects the verified current mount, not container-rebuild durability.
    os.environ['DASHBOARD_POSTGRES_PERSISTENT_DATA'] = 'true'
    os.chdir(args.app_root)
    sys.path.insert(0, str(args.app_root))
    from app.main import app
    import uvicorn
    uvicorn.run(RejectWrites(app), host='0.0.0.0' if args.sso_preview else '127.0.0.1', port=args.port, access_log=False)


if __name__ == '__main__':
    main()
