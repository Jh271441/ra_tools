"""Trusted local service adapter for the model-field audit, never a public writer.

Reads the owned running application's context using the existing sidecar adapter.
Trail writes stay in the caller or the administrator-only restore endpoint.
"""
import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ra-root', type=Path, required=True)
    parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.ra_root))
    from tools.manual_sidecar.import_runs import production_context
    settings, db = production_context()
    from app import model_field_audit as audit
    request = json.loads(args.request.read_text())
    if request['action'] == 'begin':
        changes = request['changes']
        if request['source'] == 'model_label_normalization' and any(
                c.get(audit.FIELD) != '成功' for c in changes):
            raise ValueError('Normalization only sets 成功')
        audit.begin(db, operation_id=request['operation_id'], source=request['source'],
            actor=request['actor'], actor_source='authorized_local_service',
            reason=request['reason'], rows=request['before'], changes=changes,
            after_rows=request.get('after'))
        operation = db.trail_operation(request['operation_id'])
        if operation['children']:
            raise ValueError('Restored operation cannot be replayed')
    elif request['action'] == 'finish':
        audit.reconcile(db, request['operation_id'], request['rows'])
    else:
        raise ValueError('Invalid service action')
    operation = db.trail_operation(request['operation_id'])
    print(json.dumps({'operation_id': operation['id'], 'status': operation['status'],
        'outcomes': operation['outcomes']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
