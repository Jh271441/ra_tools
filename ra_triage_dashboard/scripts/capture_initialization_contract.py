#!/usr/bin/env python3
"""Compare initialization on disposable SQLite/PostgreSQL fixtures only.

Freezes the initializer clock. Writes fixtures, never the live database. Output
contains schema and table hashes, not credentials or raw production records.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--sqlite', type=Path)
    group.add_argument('--url-file', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    sys.path.insert(0, str(args.source_root.resolve()))
    from app.db import Database
    for name, module in list(sys.modules.items()):
        if name.startswith('app.db_parts') and hasattr(module, 'utc_now'):
            module.utc_now = lambda: '2026-10-08T00:00:00+00:00'
    if args.sqlite:
        if args.sqlite.exists():
            raise ValueError('SQLite fixture must be a new file')
        target = args.sqlite
    else:
        from psycopg.conninfo import conninfo_to_dict
        target = args.url_file.read_text().strip()
        dbname = conninfo_to_dict(target)['dbname']
        if not dbname.startswith('manual_refactor') or not dbname.endswith(('_init_old', '_init_new')):
            raise ValueError('Only named disposable initialization copies are allowed')
    db = Database(target, postgres_migrations_dir=args.source_root / 'migrations/postgres', pool_size=2)

    def snapshot():
        with db.connect() as conn:
            if db.backend == 'sqlite':
                schema = [dict(x) for x in conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()]
                tables = [x['name'] for x in schema if x['type'] == 'table']
            else:
                schema = {
                    'columns': [dict(x) for x in conn.execute("SELECT table_name,column_name,ordinal_position,data_type,column_default,is_nullable FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position").fetchall()],
                    'indexes': [dict(x) for x in conn.execute("SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY tablename,indexname").fetchall()],
                    'constraints': [dict(x) for x in conn.execute("SELECT conrelid::regclass::text AS table_name,conname,pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE connamespace='public'::regnamespace ORDER BY table_name,conname").fetchall()],
                }
                tables = [x['tablename'] for x in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()]
            result = {'schema': schema, 'tables': {}}
            for table in tables:
                safe = '"' + table.replace('"', '""') + '"'
                records = [dict(x) for x in conn.execute('SELECT * FROM ' + safe).fetchall()]
                # SQLite change triggers use wall-clock strftime independently of utc_now.
                # Preserve revision counts while normalizing only that observation timestamp.
                if table == 'dashboard_change_revision':
                    for record in records:
                        record['updated_at'] = '<trigger-clock>'
                rows = [json.dumps(x, sort_keys=True, default=str) for x in records]
                result['tables'][table] = [len(rows), hashlib.sha256('\n'.join(sorted(rows)).encode()).hexdigest()]
            return result

    try:
        db.init()
        first = snapshot()
        db.init()
        second = snapshot()
        assert first['schema'] == second['schema'], 'Repeated init changed schema'
        output = {'first': first, 'second': second}
        if args.sqlite:
            # A queued inference is failed on restart; preserve the established recovery policy.
            with db.connect() as conn:
                conn.execute("INSERT INTO issues(issue_id,created_at,updated_at) VALUES ('fixture-case','fixed','fixed')")
                cols = {x['name'] for x in conn.execute('PRAGMA table_info(inference_jobs)').fetchall()}
                row = {'id': 'fixture-job', 'issue_id': 'fixture-case', 'status': 'queued', 'created_at': 'fixed'}
                row = {k: v for k, v in row.items() if k in cols}
                conn.execute('INSERT INTO inference_jobs (' + ','.join(row) + ') VALUES (' + ','.join('?' for _ in row) + ')', tuple(row.values()))
            db.init()
            with db.connect() as conn:
                assert conn.execute("SELECT status FROM inference_jobs WHERE id='fixture-job'").fetchone()['status'] == 'failed'
            output['recovery'] = snapshot()
        payload = json.dumps(output, sort_keys=True, ensure_ascii=False, default=str).encode()
        args.output.write_bytes(payload)
        print(json.dumps({'backend': db.backend, 'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}))
    finally:
        db.close()


if __name__ == '__main__':
    main()
