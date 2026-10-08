#!/usr/bin/env python3
"""Read-only behavior snapshot for comparing two source trees on one frozen DB.

The URL is read from a private file; never pass credentials in argv. This tool
never initializes schema or creates exports/decisions. Output contains private
application records and must stay outside Git in a mode-0700 evidence directory.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--url-file', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    os.environ['PGOPTIONS'] = '-c default_transaction_read_only=on'
    sys.path.insert(0, str(args.source_root.resolve()))
    from app.db import Database
    from app.labeling_summary import summarize_labeling_cases
    db = Database(args.url_file.read_text().strip(),
                  postgres_migrations_dir=args.source_root / 'migrations/postgres', pool_size=2)
    result = {}
    try:
        with db.connect() as conn:
            assert conn.execute('SHOW transaction_read_only').fetchone()[0] == 'on'
            scopes = [r['baseline_scope'] for r in conn.execute(
                'SELECT baseline_scope FROM gt_snapshot_active ORDER BY baseline_scope').fetchall()]
            result['snapshots'] = [dict(r) for r in conn.execute(
                'SELECT * FROM gt_snapshot_active ORDER BY baseline_scope').fetchall()]
        for scope in scopes:
            items, _ = db._project_labeling_cases(baseline_scopes=[scope])
            result[scope] = {
                'projection': items,
                'summary': summarize_labeling_cases(items, page_size=100),
                'candidates': db.label_gt_candidates([scope], include_non_updates=True),
                'adjudicated': db.labeling_case_issue_ids(baseline_scopes=[scope], cluster='adjudicated'),
            }
        result['run_collections'] = db.list_run_collections()
        result['run_evaluations'] = db.list_run_evaluations(limit=500)
        result['evaluation_details'] = {
            item['id']: db.get_run_evaluation_task_context(item['id'])
            for item in result['run_evaluations']
        }
        result['batches'] = db.list_review_work_splits(limit=100)
        result['details'] = {}
        for batch in result['batches']:
            pages = {}
            for status in ['all', 'completed', 'pending']:
                rows = []
                page = 1
                while True:
                    payload = db.get_review_work_split(batch['split_id'], page=page, page_size=100, status=status)
                    rows.append(payload)
                    if page * 100 >= payload['total']:
                        break
                    page += 1
                pages[status] = rows
            result['details'][batch['split_id']] = pages
        encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str).encode()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(args.output, 'wb') as stream:
            stream.write(encoded)
        receipt = {'sha256': hashlib.sha256(encoded).hexdigest(), 'bytes': len(encoded),
                   'scopes': len(scopes), 'batches': len(result['batches'])}
        args.output.with_suffix('.receipt.json').write_text(json.dumps(receipt, indent=2))
        print(json.dumps(receipt))
    finally:
        db.close()


if __name__ == '__main__':
    main()
