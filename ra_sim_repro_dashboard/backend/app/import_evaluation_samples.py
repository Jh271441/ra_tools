"""Explicit offline sample acquisition/import; never runs inside a page request.

Run from backend with the service's normal DB environment:
  python -m app.import_evaluation_samples migrate --recalculate
  python -m app.import_evaluation_samples import /private/verified-samples.json --recalculate
  python -m app.import_evaluation_samples fetch --release ... --date-start ... --date-end ...

The JSON bundle is {dashboard: <complete verified receipt>, labels: {issue_id: ...}}.
Each update replaces a complete scope, reports a diff and preserves prior versions.
Only the explicit fetch subcommand uses an upstream login; imports and page reads
do not require it. Never print credentials or raw sample payloads.
"""
import argparse
import json
import os
from pathlib import Path
from app.database import SessionLocal
from app.services import evaluation_samples as samples, evaluation_pipeline as pipeline
from app.services import auto_triage_warehouse as warehouse, auto_triage_metrics as at
from app.services import metric_profiles


def recalculate_contexts(db, releases, extra_contexts=()):
    contexts = [r['context'] for r in pipeline.rows(db, 'evcontext:') if r.get('context', {}).get('release') in releases]
    contexts = list({json.dumps(ctx,sort_keys=True):ctx for ctx in [*contexts,*extra_contexts]}.values())
    results = []
    for ctx in contexts:
        try:
            value = pipeline.recalculate(db, **ctx)
            results.append({'context': ctx, 'revision_key': value['revision_key'], 'source_count': value['source_count']})
        except ValueError as exc:
            db.rollback()
            results.append({'context': ctx, 'error': str(exc)})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    migrate = sub.add_parser('migrate', help='Promote reconciled DB receipts without network access')
    load = sub.add_parser('import', help='Validate and atomically import a complete offline JSON bundle')
    load.add_argument('file', type=Path)
    fetch = sub.add_parser('fetch', help='Explicit one-shot upstream acquisition and DB import')
    fetch_trail = sub.add_parser('fetch-trail',help='Offline Trail acquisition and atomic native-snapshot import')
    trail = sub.add_parser('verify-trail',help='Read-only Trail comparison; never imports or starts simulation')
    trail.add_argument('--reference',type=Path,required=True,help='Verified schema-2 offline bundle')
    trail.add_argument('--output',type=Path,required=True,help='New private evidence file; never overwritten')
    for item in (migrate, load, fetch, fetch_trail):
        item.add_argument('--recalculate', action='store_true', help='Reproject existing contexts; never starts simulation')
        item.add_argument('--profile', help='Explicit evaluation profile for acquisition and recalculation')
    for item in (fetch,fetch_trail):
        item.add_argument('--release', required=True)
        item.add_argument('--date-start', required=True)
        item.add_argument('--date-end', required=True)
        item.add_argument('--filters', type=Path, help='Optional JSON population filters')
    fetch_trail.add_argument('--output',type=Path,required=True,help='New private evidence bundle; never overwritten')
    args = parser.parse_args()
    if args.command == 'verify-trail':
        from app.services import evaluation_trail
        if args.output.exists():
            raise ValueError('evidence_file_exists')
        reference = json.loads(args.reference.read_text())['dashboard']
        evaluation_trail.validate_reference(reference)
        candidate = evaluation_trail.collect(reference['scope'],reference['population_filters'])
        report = evaluation_trail.verify(reference,candidate)
        descriptor = os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'w') as stream:
            json.dump({'report':report,'candidate':candidate},stream,ensure_ascii=False,indent=2)
            stream.write('\n')
        print(json.dumps({'status':report['status'],'reference_count':report['reference_count'],
                          'trail_count':report['trail_count'],'added':len(report['added_ids']),
                          'missing':len(report['missing_ids']),'changed':len(report['differences']),
                          'unresolved':len(report['unresolved']),'evidence':str(args.output),
                          'production_changes':False,'simulation_submitted':False},ensure_ascii=False,indent=2))
        return 0 if report['status'] == 'matched' else 2
    with SessionLocal() as db:
        if args.command == 'fetch-trail' and args.output.exists():
            raise ValueError('evidence_file_exists')
        if args.command == 'migrate':
            result = samples.migrate(db)
        else:
            if args.command == 'import':
                body = json.loads(args.file.read_text())
                provenance = {'kind': 'offline_file', 'file_name': args.file.name}
            else:
                profile = metric_profiles.get(db, args.profile)
                selected = samples.filters(json.loads(args.filters.read_text()) if args.filters else profile['config']['population']['filters'])
                # Validate scope before any network call.
                release = args.release
                if not at.RELEASE.fullmatch(release):
                    raise ValueError('unknown_release')
                snapshot = at._snapshot(db, release)
                scope = warehouse.scope_for(snapshot.payload['period'] if snapshot else {'release':release}, args.date_start, args.date_end)
                if args.command == 'fetch-trail':
                    from app.services import evaluation_trail
                    if profile['config']['label']['source'] != 'coalesce':
                        raise ValueError('trail_review_profile_required')
                    acquired = evaluation_trail.collect(scope,selected)
                    dashboard = evaluation_trail.receipt(acquired)
                    labels = acquired['labels']
                else:
                    dashboard = warehouse.fetch(scope, population_filters=selected,
                                                include_review=profile['config']['schema_version']==2)
                    labels = at.fetch_labels([r['issue_id'] for r in dashboard['rows']]) if dashboard['rows'] else {}
                body = {'dashboard': dashboard, 'labels': labels}
                provenance = {'kind': 'explicit_offline_acquisition','provider':dashboard.get('provider','shuyi')}
                if args.command == 'fetch-trail':
                    descriptor = os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                    with os.fdopen(descriptor,'w') as stream:
                        json.dump(body,stream,ensure_ascii=False,indent=2)
                        stream.write('\n')
            result = [samples.import_snapshot(db, body['dashboard'], body['labels'], provenance=provenance)]
        output = {'imports': result, 'simulation_submitted': False}
        if args.recalculate:
            extra = [{**r['scope'],'profile_id':args.profile} for r in result] if args.profile else []
            output['recalculations'] = recalculate_contexts(db, {r['scope']['release'] for r in result}, extra)
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    raise SystemExit(main())
