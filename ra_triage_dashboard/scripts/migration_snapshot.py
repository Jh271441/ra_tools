#!/usr/bin/env python3
"""Export a consistent read-only PostgreSQL snapshot without pruning backups.

Requires the source instance's peer-authenticated URL file. Credentials remain
on that host. The destination must be a new directory on persistent storage.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import getpass
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backup_instance import fingerprints


def main():
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url-file', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--expected-socket', type=Path, default=Path('/var/run/postgresql'))
    args = parser.parse_args()
    os.umask(0o077)
    url = args.url_file.read_text().strip()
    ci = conninfo_to_dict(url)
    socket = Path(ci.get('host') or '/var/run/postgresql')
    if ci.get('password') or not socket.is_absolute() or socket.resolve() != args.expected_socket.resolve():
        raise SystemExit('Expected explicitly pinned local peer-authentication socket')
    args.output.mkdir(parents=True, exist_ok=False)
    dump = args.output / 'database.dump'
    started = datetime.now(timezone.utc).isoformat()
    with psycopg.connect(url) as conn:
        conn.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
        snapshot = conn.execute('SELECT pg_export_snapshot()').fetchone()[0]
        subprocess.run(['pg_dump', '--host', str(socket), '--port', ci.get('port', '5432'), '--username', ci.get('user') or getpass.getuser(), '--dbname', ci['dbname'], '--format=custom',
                        '--no-owner', '--no-privileges', '--snapshot', snapshot,
                        '--file', str(dump)], check=True)
        contents = fingerprints(conn)
    subprocess.run(['pg_restore', '--list', str(dump)], check=True, stdout=subprocess.DEVNULL)
    sha = hashlib.sha256(dump.read_bytes()).hexdigest()
    receipt = {'schema_version': 1, 'source_database': ci['dbname'], 'started_at': started,
               'finished_at': datetime.now(timezone.utc).isoformat(), 'sha256': sha,
               'bytes': dump.stat().st_size, 'table_fingerprints': contents,
               'restore_verified': False, 'source_writes_frozen': False}
    (args.output / 'receipt.json').write_text(json.dumps(receipt, indent=2))
    print(json.dumps({'dump': str(dump), 'tables': len(contents), 'sha256': sha}))


if __name__ == '__main__':
    main()
