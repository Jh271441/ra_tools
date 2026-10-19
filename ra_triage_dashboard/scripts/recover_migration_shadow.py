#!/usr/bin/env python3
"""Recover the prepared cloud_server_2 shadow without changing production traffic.

Requires already provisioned packages and retained /local-data. This is a manual
recovery entrypoint, not evidence that the platform retains a rebuilt container.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT = Path('/local-data/services/manual')
MOUNTS = ('/mnt/ofs/manual-ro', '/mnt/ofs/manual-bags-ro')


def run(args, **kwargs):
    return subprocess.run(args, check=True, timeout=30, **kwargs)


def check_storage():
    mount = json.loads(subprocess.check_output(
        ['findmnt', '-J', '-T', str(ROOT), '-o', 'TARGET,FSTYPE,SOURCE'], text=True))['filesystems'][0]
    if mount['target'] != '/local-data' or mount['fstype'] != 'xfs':
        raise RuntimeError('Expected the existing /local-data XFS volume; refusing overlay fallback')
    required = ['postgresql/14/main/PG_VERSION', 'config/supervisord.conf',
                'config/shadow-env.json', 'venv/bin/python', 'bin/orangefs']
    for rel in required:
        if not (ROOT / rel).is_file():
            raise RuntimeError(f'Missing retained prerequisite: {rel}')
    env = json.loads((ROOT / 'config/shadow-env.json').read_text())
    if env.get('DASHBOARD_DEPLOYMENT_MODE') != 'production':
        raise RuntimeError('Shadow identity restrictions changed')


def mounts_ready():
    lines = [line.split() for line in Path('/proc/mounts').read_text().splitlines()]
    return all(any(row[0] == 'orangefs:remote-assist-stuck-model' and row[1] == path
                   and 'ro' in row[3].split(',') for row in lines) for path in MOUNTS)


def ensure_supervisor(config, privileged=False):
    prefix = ['sudo', '-n'] if privileged else []
    result = subprocess.run(prefix + ['supervisorctl', '-c', str(config), 'pid'],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=30)
    if result.returncode:
        run(prefix + ['supervisord', '-c', str(config)])


def ensure_program(config, name, privileged=False):
    command = (['sudo', '-n'] if privileged else []) + ['supervisorctl', '-c', str(config)]
    result = subprocess.run(command + ['status', name], text=True, stdout=subprocess.PIPE, timeout=30)
    if result.returncode or 'RUNNING' not in result.stdout:
        run(command + ['start', name])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--check', action='store_true', help='Inspect only; never start processes')
    p.add_argument('--with-sso-preview', action='store_true', help='Also recover the dedicated read-only 18786 preview')
    args = p.parse_args()
    check_storage()
    if args.with_sso_preview:
        preview = json.loads((ROOT / 'config/sso-preview-env.json').read_text())
        from run_migration_shadow import validate_config
        validate_config(preview, sso_preview=True)
        if not (ROOT / 'config/program-sso-preview.ini').is_file():
            raise RuntimeError('Missing dedicated SSO preview program')
    if not args.check:
        ensure_supervisor(ROOT / 'ofs-private/supervisord.conf', privileged=True)
        for name in ('manual-ofs-media', 'manual-ofs-bags', 'manual-ofs-backups'):
            ensure_program(ROOT / 'ofs-private/supervisord.conf', name, privileged=True)
        deadline = time.monotonic() + 60
        while not mounts_ready() and time.monotonic() < deadline:
            time.sleep(1)
    if not mounts_ready():
        raise RuntimeError('Expected both read-only OFS mounts before starting the application')
    if json.loads(Path('/mnt/ofs/manual-ro/.manual-volume.json').read_text()).get('service') != 'manual':
        raise RuntimeError('Unexpected OFS service sentinel')
    if not args.check:
        ensure_supervisor(ROOT / 'config/supervisord.conf')
        ensure_program(ROOT / 'config/supervisord.conf', 'manual-postgres')
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            result = subprocess.run(['/usr/lib/postgresql/14/bin/pg_isready', '-h', str(ROOT / 'run/postgresql'),
                                     '-p', '55432'], stdout=subprocess.DEVNULL, timeout=5)
            if not result.returncode:
                break
            time.sleep(1)
        else:
            raise RuntimeError('PostgreSQL not ready')
        ensure_program(ROOT / 'config/supervisord.conf', 'manual-shadow')
        if args.with_sso_preview:
            ensure_program(ROOT / 'config/supervisord.conf', 'manual-sso-preview')
    deadline = time.monotonic() + (1 if args.check else 90)
    while True:
        try:
            with urllib.request.urlopen('http://127.0.0.1:18785/manual/health', timeout=10) as response:
                health = json.load(response)
            assert health['ok'] and health['storage'] == 'postgresql'
            assert not any(health.get(k) for k in ('trail_write_enabled', 'trail_attribute_write_enabled',
                'trail_attribute_review_write_enabled', 'batch_prediction_enabled', 'autotriage_push_enabled'))
            if args.with_sso_preview:
                with urllib.request.urlopen('http://127.0.0.1:18786/manual-migration/health', timeout=10) as response:
                    preview_health = json.load(response)
                assert preview_health['ok'] and preview_health['storage'] == 'postgresql'
                assert preview_health['base_path'] == '/manual-migration'
                with urllib.request.urlopen('http://127.0.0.1:18786/manual-migration/api/session', timeout=10) as response:
                    preview_session = json.load(response)
                assert preview_session['read_only'] and not preview_session['verified']
            if not args.check and (ROOT / 'config/program-backup.ini').is_file():
                from migration_backup_replica import check_mount
                check_mount()
                ensure_program(ROOT / 'config/supervisord.conf', 'manual-backup')
            print(json.dumps({'ok': True, 'shadow_only': True, 'mounts_read_only': True,
                              'sso_preview_checked': args.with_sso_preview,
                              'container_rebuild_durability': 'unverified'}))
            return
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)


if __name__ == '__main__':
    main()
