#!/usr/bin/env python3
"""Prepare, apply, or activate an audited 1106+ cutover. Never writes Trail.

Run with -m ra_triage_dashboard.scripts.migrate_human_labels from the checkout.
First rehearse on a restored backup with migration 061 installed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat

from ra_triage_dashboard.app.db import Database
from ra_triage_dashboard.app.human_label_migration import migration_plan,apply_migration,arm_migrated_sources
from ra_triage_dashboard.app.human_publisher import qualified_capabilities


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    dbgroup=parser.add_mutually_exclusive_group(required=True)
    dbgroup.add_argument('--sqlite',type=Path)
    dbgroup.add_argument('--database-url-file',type=Path)
    parser.add_argument('--dataset',required=True)
    parser.add_argument('--action',choices=['plan','apply','arm'],default='plan')
    parser.add_argument('--reviewed-report',type=Path)
    parser.add_argument('--backup',type=Path)
    parser.add_argument('--historical-role',choices=['rd','te'])
    parser.add_argument('--actor')
    parser.add_argument('--capabilities',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists():parser.error('Output already exists; choose a new receipt path')
    if args.database_url_file:
        if stat.S_IMODE(args.database_url_file.stat().st_mode)&0o077:parser.error('Database URL file must be private')
        target=args.database_url_file.read_text().strip()
    else:
        if not args.sqlite.is_file():parser.error('Existing restored SQLite database required')
        target=args.sqlite
    database=Database(target,postgres_migrations_dir=Path(__file__).resolve().parents[1]/'migrations/postgres')
    try:
        if args.action=='plan':result=migration_plan(database,args.dataset)
        else:
            if not args.reviewed_report or not args.actor:parser.error('Reviewed report and administrator actor required')
            report=json.loads(args.reviewed_report.read_text())
            if report.get('dataset_id')!=args.dataset:parser.error('Reviewed report belongs to another dataset')
            fingerprint=report.get('source_fingerprint') or report.get('fingerprint')
            if args.action=='apply':
                if not args.backup or not args.backup.is_file():parser.error('Verified logical backup file required')
                sha=hashlib.sha256()
                with args.backup.open('rb') as file:
                    for chunk in iter(lambda:file.read(1024*1024),b''):sha.update(chunk)
                result=apply_migration(database,dataset_id=args.dataset,expected_fingerprint=fingerprint,
                    backup_sha256=sha.hexdigest(),actor=args.actor,historical_role=args.historical_role)
            else:
                qualified_capabilities(args.capabilities)
                result=arm_migrated_sources(database,dataset_id=args.dataset,source_fingerprint=fingerprint,actor=args.actor)
        with os.fdopen(os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as file:
            json.dump(result,file,ensure_ascii=False,indent=2,default=str)
        print(json.dumps({k:v for k,v in result.items() if k not in {'source','archive','missing_role_evidence'}},ensure_ascii=False,default=str))
    finally:database.close()


if __name__=='__main__':main()
