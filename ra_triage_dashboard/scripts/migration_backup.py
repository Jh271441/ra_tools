#!/usr/bin/env python3
"""Bounded verified backup for the prepared Manual target.

Creates a new generation on the retained local volume. A generation is complete
only after database restore and attachment archive verification both pass.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import uuid

from backup_instance import fingerprints

ROOT = Path('/local-data/services/manual')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            h.update(block)
    return h.hexdigest()


def main():
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--expected-database', required=True)
    args = p.parse_args()
    os.umask(0o077)
    if not re.fullmatch(r'manual_[a-z0-9_]{1,50}', args.expected_database):
        raise ValueError('Explicit Manual database name required')
    env = json.loads(args.config.read_text())
    data = Path(env['DASHBOARD_DATA_DIR']).resolve()
    if not data.is_relative_to(ROOT):
        raise ValueError('State must be below the pinned Manual root')
    ci = conninfo_to_dict(Path(env['DASHBOARD_DATABASE_URL_FILE']).read_text().strip())
    if ci.get('host') != str(ROOT / 'run/postgresql') or ci.get('port') != '55432' or ci.get('password') or ci.get('dbname') != args.expected_database:
        raise ValueError('Unexpected database identity or connection')
    fs = json.loads(subprocess.check_output(['findmnt', '-J', '-T', str(data), '-o', 'TARGET,FSTYPE'], text=True))['filesystems'][0]
    if fs['target'] != '/local-data' or fs['fstype'] != 'xfs':
        raise ValueError('Refusing a missing or overlay-backed state volume')
    base = data / 'postgres_backups' / 'scheduled'
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (base / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        used = sum(f.stat().st_size for f in base.rglob('*') if f.is_file())
        free = os.statvfs(base).f_bavail * os.statvfs(base).f_frsize
        if used > 18 * 1024**3 or free < 5 * 1024**3:
            raise RuntimeError('Backup capacity gate; no existing backups were deleted')
        dest = base / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
        dest.mkdir(mode=0o700)
        dump = dest / 'database.dump'
        common = ['--host', ci['host'], '--port', ci['port'], '--username', ci['user']]
        with psycopg.connect(**ci) as conn:
            conn.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
            snapshot = conn.execute('SELECT pg_export_snapshot()').fetchone()[0]
            before = fingerprints(conn)
            subprocess.run(['pg_dump', *common, '--dbname', ci['dbname'], '--format=custom', '--no-owner', '--no-privileges', '--snapshot', snapshot, '--file', str(dump)], check=True)
        subprocess.run(['pg_restore', '--list', str(dump)], stdout=subprocess.DEVNULL, check=True)
        attachments = []
        for name in ('review_attachments', 'comment_attachments', 'uploads'):
            root = data / name
            if root.is_dir():
                for path in root.rglob('*'):
                    if path.is_symlink():
                        raise ValueError('Attachment symlinks are not accepted')
                    if path.is_file():
                        st = path.stat()
                        attachments.append({'path': str(path.relative_to(data)), 'size': st.st_size, 'mtime_ns': st.st_mtime_ns, 'sha256': digest(path)})
        archive = dest / 'attachments.tar.gz'
        with tarfile.open(archive, 'w:gz') as out:
            for row in attachments:
                out.add(data / row['path'], arcname=row['path'], recursive=False)
        with tarfile.open(archive, 'r:gz') as inp:
            for row in attachments:
                member = inp.getmember(row['path'])
                with inp.extractfile(member) as f:
                    h = hashlib.sha256()
                    for chunk in iter(lambda: f.read(4 * 1024**2), b''): h.update(chunk)
                st = (data / row['path']).stat()
                if member.size != row['size'] or h.hexdigest() != row['sha256'] or (st.st_size, st.st_mtime_ns) != (row['size'], row['mtime_ns']):
                    raise RuntimeError('Attachments changed during backup; generation left incomplete')
        restore = 'manual_restorecheck_' + uuid.uuid4().hex[:16]
        admin_ci = {**ci, 'dbname': 'postgres', 'user': 'didi'}
        with psycopg.connect(**admin_ci, autocommit=True) as admin:
            admin.execute(sql.SQL('CREATE DATABASE {} WITH TEMPLATE template0 OWNER {}').format(sql.Identifier(restore), sql.Identifier(ci['user'])))
        try:
            subprocess.run(['pg_restore', *common, '--dbname', restore, '--no-owner', '--no-privileges', '--exit-on-error', str(dump)], check=True)
            with psycopg.connect(**{**ci, 'dbname': restore}) as check:
                check.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
                after = fingerprints(check)
            if before != after:
                raise RuntimeError('Restored database differs from exported snapshot')
        finally:
            with psycopg.connect(**admin_ci, autocommit=True) as admin:
                admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(restore)))
        receipt = {'database': ci['dbname'], 'created_at': datetime.now(timezone.utc).isoformat(), 'complete': True,
                   'dump_sha256': digest(dump), 'assets_sha256': digest(archive), 'attachments': attachments,
                   'table_fingerprints': after, 'restore_verified': True, 'off_host_replica_verified': False,
                   'consistency_scope': 'consistent database snapshot plus stable copied attachments; final cutover still requires a write freeze'}
        (dest / 'receipt.json').write_text(json.dumps(receipt, indent=2))
        from migration_backup_replica import replicate
        replica = replicate(dest)
        print(json.dumps({'generation': str(dest), 'tables': len(after), 'attachments': len(attachments), 'restore_verified': True, **replica}), flush=True)


if __name__ == '__main__':
    main()
