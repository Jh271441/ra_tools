#!/usr/bin/env python3
"""Compare read-only intent membership and per-frame timelines across a migration."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root', type=Path, required=True)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--source-live', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if bool(args.env_file) == args.source_live:
        raise ValueError('Choose one environment source')
    if args.source_live:
        spec = importlib.util.spec_from_file_location('deploy', args.app_root/'scripts/deploy_cloud.py')
        deploy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(deploy)
        _, env = deploy.read_live()
    else:
        env = json.loads(args.env_file.read_text())
    # No credentials are copied to the process environment or report.
    os.environ.update({k: v for k, v in env.items() if k.startswith('DASHBOARD_INTENT_') and isinstance(v, str)})
    sys.path.insert(0, str(args.app_root))
    from app.intent_dataset_registry import IntentDatasetIndex
    config = Path(env.get('DASHBOARD_INTENT_DATASETS_FILE', str(args.app_root/'config/intent_datasets.json')))
    index = IntentDatasetIndex.from_file(config)
    start = time.monotonic()
    index.refresh()
    if not index.public_datasets():
        raise ValueError('No intent datasets registered')
    result = {'datasets': {}, 'samples': {}, 'scope': 'All intent memberships and frame pairing, sampled asset bytes; no DB/SSO or writes'}
    for public in index.public_datasets():
        name = public['id']
        cases = index.case_ids(name)
        if not cases:
            raise ValueError(f'No indexed cases for {name}; refusing an empty contract')
        signatures = {}; missing_bev = []; missing_camera = []
        for case in cases:
            timeline = index.timeline(name, case)
            normalized = [{'offset_ms': row['offset_ms'], 'bev': bool(row['bev']),
                           'camera': bool(row['camera']), 'camera_delta_ms': row['camera_delta_ms']}
                          for row in timeline]
            signatures[case] = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
            if not any(row['bev'] for row in timeline): missing_bev.append(case)
            if not any(row['camera'] for row in timeline): missing_camera.append(case)
        result['datasets'][name] = {'case_count': len(cases), 'membership_sha256': index.membership_sha256(name),
                                   'case_timeline_sha256': signatures, 'missing_bev': missing_bev, 'missing_camera': missing_camera}
        chosen = sorted(set([cases[0], cases[len(cases)//2], cases[-1]])) if cases else []
        for case in chosen:
            timeline = index.timeline(name, case)
            for kind in ('bev', 'camera'):
                rows = [row for row in timeline if row[kind]]
                if not rows: continue
                for row in [rows[0], rows[len(rows)//2], rows[-1]]:
                    asset = row[kind]['asset_id']
                    path, media_type = index.resolve_asset(name, case, asset)
                    result['samples'][f'{name}/{case}/{asset}'] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                                                'bytes': path.stat().st_size, 'media_type': media_type}
    result['seconds'] = time.monotonic()-start
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'datasets': {k: {f: v[f] for f in ('case_count','membership_sha256')} for k,v in result['datasets'].items()},
                      'sampled_assets': len(result['samples']), 'seconds': result['seconds']}))


if __name__ == '__main__':
    main()
