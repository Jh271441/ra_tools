#!/usr/bin/env python3
"""Back up one pinned PostgreSQL instance; optional exact-snapshot restore rehearsal.

Only local peer-authenticated PostgreSQL is supported. Never changes the live DB.
Install this outside an immutable source tree, and schedule with its --instance.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import uuid


def fingerprints(conn):
    from psycopg import sql
    result = {}
    tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
    for (table,) in tables:
        records = conn.execute(sql.SQL('SELECT row_to_json(t)::text FROM {} t').format(sql.Identifier(table))).fetchall()
        hashes = sorted(hashlib.sha256(json.dumps(json.loads(row[0]), sort_keys=True, separators=(',', ':')).encode()).hexdigest() for row in records)
        result[table] = {'count': len(hashes), 'sha256': hashlib.sha256('\n'.join(hashes).encode()).hexdigest()}
    return result


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--instance', required=True, type=Path)
    p.add_argument('--verify', action='store_true')
    args = p.parse_args()
    os.umask(0o077)
    root = args.instance.resolve()
    config = json.loads((root/'config/service_env.json').read_text())
    url = Path(config['DASHBOARD_DATABASE_URL_FILE']).read_text().strip()
    ci = conninfo_to_dict(url)
    name = ci.get('dbname', '')
    if not re.fullmatch('[a-z_][a-z0-9_]{0,62}', name) or ci.get('password') or ci.get('host', '').strip('/') not in {'', 'var/run/postgresql'} or ci.get('port', '5432') != '5432':
        raise SystemExit('Only local peer-authenticated database backups are supported')
    data = Path(config['DASHBOARD_DATA_DIR']).resolve()
    if not data.is_relative_to('/volume'):
        raise SystemExit('Backup data directory must be on /volume')
    dest = data/'postgres_backups'
    dest.mkdir(mode=0o700, exist_ok=True)
    if subprocess.check_output(['findmnt', '-n', '-o', 'FSTYPE', '-T', str(dest)], text=True).strip() == 'overlay':
        raise SystemExit('Refusing overlay backups')
    with (dest/'.backup.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        dump = dest/f'{name}-{stamp}.dump'
        temp = dest/f'.{name}-{uuid.uuid4().hex}.dump'
        if dump.exists():
            raise SystemExit('Backup already exists for this second')
        try:
            with psycopg.connect(url) as conn:
                conn.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
                snapshot = conn.execute('SELECT pg_export_snapshot()').fetchone()[0]
                before = fingerprints(conn) if args.verify else None
                run('pg_dump', '--dbname', name, '--format=custom', '--no-owner', '--no-privileges', '--snapshot', snapshot, '--file', str(temp))
            run('pg_restore', '--list', str(temp), stdout=subprocess.DEVNULL)
            temp.rename(dump)
        finally:
            temp.unlink(missing_ok=True)
        checksum = hashlib.sha256(dump.read_bytes()).hexdigest()
        dump.with_suffix('.dump.sha256').write_text(f'{checksum}  {dump.name}\n')
        receipt = {'database': name, 'dump': dump.name, 'sha256': checksum, 'created_at': stamp, 'restore_verified': False}
        # Include mutable attachment directories in the same backup generation.
        assets = [x for x in ['review_attachments', 'comment_attachments', 'uploads'] if (data/x).is_dir()]
        if assets:
            asset_file = dump.with_suffix('.assets.tar.gz')
            run('tar', '-czf', str(asset_file), '-C', str(data), *assets)
            receipt['assets'] = {'file': asset_file.name, 'sha256': hashlib.sha256(asset_file.read_bytes()).hexdigest()}
        if args.verify:
            restore = 'manual_restorecheck_' + uuid.uuid4().hex[:16]
            owner = ci.get('user') or os.getenv('USER')
            run('sudo', '-u', 'postgres', 'createdb', '--template=template0', '--owner', owner, restore, stdout=subprocess.DEVNULL)
            try:
                run('pg_restore', '--dbname', restore, '--no-owner', '--no-privileges', '--exit-on-error', str(dump))
                with psycopg.connect(dbname=restore) as conn:
                    conn.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
                    after = fingerprints(conn)
                if before != after:
                    raise RuntimeError('Restored contents differ from exported source snapshot')
                receipt.update(restore_verified=True, table_fingerprints=after)
            finally:
                run('sudo', '-u', 'postgres', 'dropdb', '--if-exists', restore, stdout=subprocess.DEVNULL)
        dump.with_suffix('.receipt.json').write_text(json.dumps(receipt, indent=2))
        # Retain 14 complete generations, never touch other database names.
        complete = sorted(dest.glob(f'{name}-????????T??????Z.dump'), reverse=True)
        for old in complete[14:]:
            for file in [old, old.with_suffix('.dump.sha256'), old.with_suffix('.assets.tar.gz'), old.with_suffix('.receipt.json')]:
                file.unlink(missing_ok=True)
        print(json.dumps({'database': name, 'dump': str(dump), 'restore_verified': receipt['restore_verified'], 'tables': len(before or {})}))


if __name__ == '__main__':
    main()
