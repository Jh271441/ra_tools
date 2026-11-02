"""Existing Ares high-level CLI with a promoted text-tool overlay for new work.

This wrapper leaves the official mapper, frozen rendering code, layout, native
submission guards, retries and downloads in Ares. No Bag is uploaded here.
"""
import json
import copy
import hashlib
import os
import re
from pathlib import Path
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
# The installed venv wheel can lag the canonical, pinned production checkout.
sys.path.insert(0, '/volume/home/workspace/ra_auto_triage')

from ra_triage_dashboard.app.planning_text_artifact import digest, identity
from ra_triage_dashboard.app.planning_text_daily import register_owner
from ra_triage_dashboard.app.planning_constraint_index import _read_history_window
from ra_triage_dashboard.scripts.planning_text.bundle import build, source_manifest, BASE_SHA
from ra_triage_dashboard.scripts.planning_text.hook import save

CONTROL = Path('/volume/home/workspace/ra_triage_dashboard_deploy/operations/bev-closeup-full-20261029/planning-text/control.json')


def selected_control(path=None):
    path = Path(path or os.environ.get('PLANNING_TEXT_CONTROL', str(CONTROL)))
    if not path.exists():
        return None
    value = json.loads(path.read_text())
    if value.get('enabled') is not True:
        return None
    code = Path(value['code'])
    _, sha = source_manifest(code)
    if sha != value['worker_source_sha256'] or digest(value['base_tool']) != BASE_SHA:
        raise ValueError('planning_promoted_code_changed')
    for name, expected in value.get('code_sha256', {}).items():
        target = (code/name).resolve()
        target.relative_to(code.resolve())
        if digest(target) != expected:
            raise ValueError('planning_promoted_code_changed')
    return value


def members_for(config, profile, lane, *, claim=True):
    rows = json.loads(Path(config['source_rows']).read_text())
    members = []
    original_rows, version_context = {}, {}
    if '--source-rows' in sys.argv:
        source = Path(sys.argv[sys.argv.index('--source-rows')+1])
        original_rows = {(r['issue_id'], r['trip_id'], r['capture_timestamp_ms']): r
                         for r in json.loads(source.read_text())}
        context_path = source.with_name('version-context.json')
        if context_path.is_file():
            version_context = json.loads(context_path.read_text())
            family = version_context.get('family', '')
            if not re.fullmatch(r'20[0-9]{6}', family) or version_context.get('dataset_id') != 'version-'+family:
                raise ValueError('planning_version_context_mismatch')
    for row in rows:
        iid, trip, anchor = row['issue_id'], row['trip_id'], row['capture_timestamp_ms']
        metadata = original_rows.get((iid, trip, anchor), row)
        version = row.get('version') or row.get('release_family') or metadata.get('version') or metadata.get('release_family') or version_context.get('family')
        if version is None:
            # This is the source membership, not an inferred capture or version.
            version = profile.get('membership', {}).get(iid, {}).get('version')
        datasets = row.get('datasets') or metadata.get('datasets') or ([version_context['dataset_id']] if version_context else profile.get('membership', {}).get(iid, {}).get('datasets', []))
        if version is None:
            raise ValueError('planning_authoritative_version_missing')
        member = dict(issue_id=iid, trip_id=trip, anchor_ms=anchor, version=str(version), datasets=datasets)
        key = identity(member)
        historical = _read_history_window(Path(profile['data_dir']), iid, 0, trip_id=trip, anchor_ms=anchor)
        if historical is not None:
            if historical.get('status') != 'ready':
                raise ValueError('planning_history_requires_review')
            member.update(owner='historical:'+key, extract=False)
        else:
            owner = lane+':'+hashlib.sha256(config['output'].encode()).hexdigest()[:16]+':'+key
            context = dict(run=config['output'], lane=lane, worker_source_sha256=profile['worker_source_sha256'])
            claimed = register_owner(profile['data_dir'], member, owner, context=context) if claim else dict(owner=owner, claimed=True, state='pending')
            if claim and not claimed['claimed'] and claimed['state'] == 'pending':
                from ra_triage_dashboard.scripts.planning_text.ownership import reconcile
                try:
                    if reconcile(profile, member, owner, context):
                        claimed = dict(owner=owner, claimed=True, state='pending')
                except Exception as exc:
                    save(Path(config['output'])/'.control/planning-text'/('owner-wait-'+key+'.json'),
                         dict(state='owner_reconciliation_wait', error_type=type(exc).__name__))
            member.update(owner=claimed['owner'], extract=claimed['claimed'] and claimed['state']=='pending')
        members.append(member)
    return members


def overlay_config(config, profile):
    from ares_animation.distribution.tool_artifact import publish_tool_artifact
    import ares_animation.workflow as workflow
    root = Path(config['output']).resolve()
    control = root/'.control/planning-text'
    lane = 'bev-closeup' if config.get('video', {}).get('size') == '1920x1080' else 'bev-original'
    submit_intent = config['target'] == 'local' or '--submit' in sys.argv
    members = members_for(config, profile, lane, claim=submit_intent)
    control.mkdir(parents=True, exist_ok=True)
    save(control/('members.json' if submit_intent else 'members.preview.json'), members)
    if config['target'] == 'orion':
        archive = control/('tool.tar.gz' if submit_intent else 'tool.preview.tar.gz')
        receipt = control/'tool.receipt.json'
        if not archive.exists():
            build(profile['base_tool'], profile['code'], members, archive)
        else:
            import tarfile
            with tarfile.open(archive) as stream:
                old = json.load(stream.extractfile('planning-worker-manifest.json'))
            if old['members'] != members or old['worker_source_sha256'] != profile['worker_source_sha256']:
                raise ValueError('planning_overlay_identity_changed')
        if not submit_intent:
            published = dict(locator='dry-run:'+digest(archive), sha256=digest(archive))
        elif receipt.exists():
            published = json.loads(receipt.read_text())
            if published.get('status') != 'published' or published.get('sha256') != digest(archive):
                raise ValueError('planning_overlay_publication_unknown')
        else:
            published = publish_tool_artifact(archive, name='planning_text_'+digest(archive)[:24],
                region='CN', receipt=receipt, expected_user='jasperchen', expected_team='Robotaxi & Map')
        config['orion']['tool_bundle_locator'] = published['locator']
        save(control/('overlay.json' if submit_intent else 'overlay.preview.json'), dict(base_release=config['orion'].get('release'),
            worker_source_sha256=profile['worker_source_sha256'], tool_sha256=published['sha256'],
            tool_locator=published['locator'], source_rows_sha256=digest(config['source_rows'])))
    else:
        from ra_triage_dashboard.scripts.planning_text.hook import before_reduce
        original = workflow.prepare_with_voyager
        by_identity = {m['trip_id']: m for m in members}
        if len(by_identity) != len(members):
            raise ValueError('planning_local_requires_unique_capture_per_trip')
        manifest = {k: profile[k] for k in ['worker_source_sha256']}
        manifest.update(base_tool_sha256=BASE_SHA, members=members)
        save(control/'manifest.json', manifest)
        os.environ['PLANNING_TEXT_MANIFEST'] = str(control/'manifest.json')
        os.environ['PLANNING_TEXT_SHARED_LOCK'] = str(Path(profile['data_dir'])/'planning_constraints/worker.lock')
        def prepare(**kwargs):
            member = by_identity[kwargs['trip_id']]
            local_context = control/'local-context.json'
            save(local_context, dict(member=member, producer=dict(kind='local', attempt_id=str(root))))
            os.environ['PLANNING_TEXT_LOCAL_CONTEXT'] = str(local_context)
            before_reduce(kwargs['input_bags'], kwargs['trip_id'], kwargs['output'],
                          already_reduced=kwargs.get('already_reduced', False))
            return original(**kwargs)
        workflow.prepare_with_voyager = prepare
    registry = Path(profile['data_dir'])/'planning_constraints/runs'
    if not submit_intent:
        return config
    save(registry/(digest(config['source_rows'])+'-'+hashlib.sha256(str(root).encode()).hexdigest()[:16]+'-'+lane+'.json'),
         dict(run=str(root), lane=lane, members=members, worker_source_sha256=profile['worker_source_sha256']))
    return config


def install():
    from ares_animation import cli
    try:
        profile = selected_control()
    except Exception:
        print('Planning text control requires review; using unchanged media pipeline.', file=sys.stderr)
        profile = None
    if profile:
        original = cli.run_workflow
        def run(config, **kwargs):
            baseline = copy.deepcopy(config)
            try:
                configured = overlay_config(config, profile)
            except Exception as exc:
                save(Path(config['output'])/'.control/planning-text/error.json',
                     dict(state='text_requires_review', code=type(exc).__name__,
                          missing_module=exc.name if isinstance(exc, ModuleNotFoundError) else None))
                with (Path(config['output'])/'.control/planning-text/error.private.log').open('a') as log:
                    traceback.print_exc(file=log)
                configured = baseline
            return original(configured, **kwargs)
        cli.run_workflow = run
    return cli


def main():
    return install().main()


if __name__ == '__main__':
    raise SystemExit(main())
