import json
from pathlib import Path
import shutil
import subprocess
import pytest

from ra_triage_dashboard.app.db import Database


@pytest.mark.skipif(not shutil.which('node'), reason='Node is required')
def test_raw_gt_display_and_review_route_preserve_classifier_contract():
    root = Path(__file__).resolve().parents[1] / 'static/js'
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const root = process.argv[1];
const core = fs.readFileSync(root + '/core-base.js', 'utf8');
vm.runInThisContext(core.slice(core.indexOf('const LABELS ='), core.indexOf('const ANALYSIS_COMPARISON_STATUSES')));
const routing = fs.readFileSync(root + '/routing.js', 'utf8');
vm.runInThisContext(routing.slice(routing.indexOf('function normalizedGtRelationFilters('), routing.indexOf('function selectedReviewLabelStates(')));
vm.runInThisContext(routing.slice(routing.indexOf('function normalizedReviewRouteFilters('), routing.indexOf('function normalizedAnalysisRouteFilters(')));
global.parseFilterList = value => String(value || '').split(',').filter(Boolean);
const filters = normalizedReviewRouteFilters(new URLSearchParams({
  gt: 'out_of_scope,未接起,误触发,unsupported',
  model_label: 'out_of_scope,未接起,正确触发',
  work_assignee: 'owner', work_split: 'campaign-test', page: '2'
}));
assert.deepEqual(filters.gtLabel, ['out_of_scope', '未接起', '误触发']);
assert.deepEqual(filters.modelLabel, ['正确触发']);
assert.deepEqual(filters.workAssignee, ['owner']);
assert.equal(filters.workSplitId, 'campaign-test');
assert.equal(filters.casePage, 2);
assert.equal(gtDisplayLabel({gt_label:'', gt_raw_label:'out_of_scope'}), 'out_of_scope');
assert.equal(gtDisplayLabel({gt_raw_label:'未接起'}), '未接起');
assert.equal(gtDisplayLabel({gt_label:'正确触发', gt_raw_label:'out_of_scope'}), '正确触发');
assert.equal(gtDisplayLabel({gt_raw_label:'unsupported'}), '');
assert.equal(gtDisplayLabel(null), '');
assert.equal(modelLabelMatchesGt('误触发', 'out_of_scope'), false);
assert.equal(modelLabelMatchesGt('真实卡住', '未接起'), false);
assert.equal(modelLabelMatchesGt('真实卡住', '正确触发'), true);
assert.deepEqual(LABELS, ['误触发', '正确触发', '无需协助']);
'''
    result = subprocess.run(['node', '-e', script, str(root)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_raw_gt_roundtrip_filter_pagination_and_snapshot_history(tmp_path):
    db = Database(tmp_path / 'raw.sqlite3')
    db.init()
    ids = ['cn1', 'cn2', 'cn3', 'cn4']
    db.replace_baseline_scope(scope='raw-test', rows=[{'issue_id': i} for i in ids], source='test')
    run, _ = db.import_model_run(name='test', source_name='test', source_sha256='a'*64,
        metadata={}, rows=[{'issue_id': i, 'model_label': '误触发'} for i in ids])
    def apply(raw, rows=None):
        return db.apply_gt_sync_snapshot(scope='raw-test', rows=rows or [{'issue_id': 'cn1', 'gt_label': '误触发'}],
            source_name='Trail', source_view_id=1000, source_field='ra_merge_result', trigger='test',
            requested_by='test', requested_by_source='test', requested_by_verified=False,
            expected_issue_ids=ids, allow_sparse=True, raw_labels=raw)
    try:
        apply({'cn2': 'out_of_scope', 'cn3': '未接起'})
        first = db.get_active_gt_snapshot('raw-test')
        assert first['valid_label_count'] == 1
        assert 'raw_gt_values' not in first['source_metadata']  # no scope-sized public payload
        assert db.get_case('cn2')['gt_raw_label'] == 'out_of_scope'
        assert db.get_case('cn3')['gt_raw_label'] == '未接起'
        assert db.get_case('cn2')['gt_label'] == ''
        assert db.list_case_issue_ids(gt_label='out_of_scope') == ['cn2']
        assert db.list_case_issue_ids(gt_label='未接起') == ['cn3']
        assert db.list_case_issue_ids(gt_label='误触发,out_of_scope') == ['cn1', 'cn2']
        page = db.list_cases(gt_label='out_of_scope,未接起', page_size=1, page=2)
        assert page['total'] == 2 and page['items'][0]['gt_raw_label'] == '未接起'
        assert db.list_case_issue_ids(gt_label='out_of_scope', model_run_id=run['id'], comparison_status='mismatch') == []
        assert db.list_case_issue_ids(gt_label='out_of_scope', model_run_id=run['id'], comparison_status='no_gt') == ['cn2']
        with pytest.raises(ValueError):
            db.list_cases(gt_label='invalid')
        revision = db.change_revision()
        apply({'cn2': 'out_of_scope', 'cn3': '未接起'})
        assert db.get_active_gt_snapshot('raw-test')['id'] == first['id']
        assert db.change_revision() == revision
        apply({'cn2': '未接起'})
        assert db.get_active_gt_snapshot('raw-test')['id'] != first['id']
        assert db.get_case('cn3')['gt_raw_label'] == ''
        assert db.list_case_issue_ids(gt_label='out_of_scope') == []
        with db.connect() as conn:
            old = conn.execute('SELECT source_metadata_json FROM gt_snapshots WHERE id = ?', (first['id'],)).fetchone()
        assert json.loads(old[0])['raw_gt_values'] == {'cn2': 'out_of_scope', 'cn3': '未接起'}
        previous = db.get_active_gt_snapshot('raw-test')['id']
        with pytest.raises(ValueError):
            apply({'cn1': '未接起'})
        assert db.get_active_gt_snapshot('raw-test')['id'] == previous
        apply({}, [{'issue_id': 'cn2', 'gt_label': '正确触发'}])
        assert db.get_case('cn2')['gt_raw_label'] == ''
        assert db.get_case('cn2')['gt_label'] == '正确触发'
    finally:
        db.close()
