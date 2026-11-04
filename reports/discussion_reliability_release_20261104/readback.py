"""Read-only production release and comment evidence check; no credentials."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.request

phase = sys.argv[1]
expected = sys.argv[2] if len(sys.argv) > 2 else ''
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def read(path):
    with opener.open('http://127.0.0.1:8785' + path, timeout=15) as response:
        return response.read()
def get(path):
    return json.loads(read(path))
def status(path):
    try:
        with opener.open('http://127.0.0.1:8785' + path, timeout=12) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
health = get('/health')
state = get('/api/status')
thread = get('/api/cases/cn37255025/discussion')
shell = read('/').decode()
result = {
    'observed_at': datetime.now(timezone.utc).isoformat(), 'phase': phase,
    'health': {key: health.get(key) for key in ('ok', 'build_commit', 'base_path', 'storage', 'deployment_mode',
        'trail_write_enabled', 'trail_attribute_write_enabled', 'trail_attribute_review_write_enabled',
        'trail_rd_write_enabled', 'batch_prediction_enabled', 'autotriage_push_enabled')},
    'database': {key: state.get('database', {}).get(key) for key in ('ok', 'persistent_data', 'migration_count')},
    'overall': state.get('overall', {}).get('status'),
    'cache_versions': sorted(set(re.findall(r'manual-triage-\d+', shell))),
    'comments': [{'id': item['id'], 'reply_to_id': item.get('reply_to_id'),
        'body_sha256': hashlib.sha256(item.get('body', '').encode()).hexdigest(),
        'created_at': item.get('created_at'), 'attachments': len(item.get('attachments', []))}
        for item in thread['comments']],
}
if expected:
    assert health['build_commit'] == expected and health['ok'] is True
    assert result['database'] == {'ok': True, 'persistent_data': True, 'migration_count': 60}
    assert result['overall'] == 'healthy'
    assert result['cache_versions'] == ['manual-triage-758']
    root = next(item for item in thread['comments'] if item['id'] == 182)
    assert len(root['attachments']) == 1, 'Expected exact historical label evidence'
    image_url = root['attachments'][0]['url']
    assert '/api/labeling/attachments/' in image_url
    result['anonymous_label_image_status'] = status(image_url)
    result['anonymous_receipt_status'] = status('/api/cases/cn37255025/discussion-submissions/release-check-0001')
    assert result['anonymous_label_image_status'] == 403
    assert result['anonymous_receipt_status'] == 403
    paths = ['static/app.js', 'static/css/review-comment.css', 'static/js/analysis.js',
        'static/js/format-api.js', 'static/js/review-mentions.js', 'static/js/i18n.js',
        'static/js/i18n-messages.js', 'static/js/routing.js']
    assets = []
    for path in paths:
        actual = read('/' + path)
        source = subprocess.check_output(['git', 'show', expected + ':ra_triage_dashboard/' + path], cwd='/volume/home/workspace/ra_tools')
        assert actual == source, 'Served resource differs: ' + path
        assets.append({'path': path, 'sha256': hashlib.sha256(actual).hexdigest()})
    result['served_assets_match'] = assets
print(json.dumps(result, ensure_ascii=False, indent=2))
