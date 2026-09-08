import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from ra_triage_dashboard.app.comparison_inputs import case_input_projection
from ra_triage_dashboard.app.db import Database


def test_saved_input_and_reference_identity():
    prompt = '中文 <|image_pad|>\n<script> &\n'
    extra = {'prompt_text': prompt, 'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
             'reason_generated': False, 'image_inputs': [{'image': 'file:///nfs/private/frame0.jpg', 'offset_sec': 0}, {'image': 'file:///nfs/private/frame1.jpg'}],
             'input_config': {'api_key': 'secret', 'nested': {'path': '/nfs/private/a'}, 'offsets': [0,1]}}
    detail = case_input_projection({}, extra, 'source-sha')
    assert detail['prompt']['text'] == prompt
    assert detail['prompt']['source_type'] == 'actual_input'
    assert detail['prompt']['computed_sha256'] == detail['prompt']['sha256']
    assert detail['reason_status'] == 'not_generated'
    assert detail['media']['count'] == 2
    assert detail['media']['items'][0]['reference_sha256'] != detail['media']['items'][1]['reference_sha256']
    assert detail['media']['items'][0]['content_sha256'] == ''
    assert '/nfs/' not in json.dumps(detail)
    assert detail['input']['config']['api_key'] == '[REDACTED]'


def test_missing_does_not_reconstruct():
    result = case_input_projection({'prompt_template':'not actual'}, {}, '')
    assert result['prompt']['source_type'] == 'not_saved'
    assert result['input']['source_type'] == 'not_saved'
    assert result['media']['count'] is None


def test_case_membership_and_run_reference(tmp_path):
    db = Database(tmp_path / 'test.db'); db.init()
    db.upsert_issues([{'issue_id':'cn1','gt_label':'误触发'}], source='test', replace_gt=True, baseline_scope='scope')
    run, _ = db.import_model_run(name='r',source_name='r.json',source_sha256='source',
        metadata={'prompt_template':'example', 'prompt_mode':'rendered_example_before_image_expansion',
                  'input_config':{'run_prompt_is_rendered_example_for_issue':'cn2'}},
        rows=[{'issue_id':'cn1','model_label':'误触发','raw':{'model_extra':{'prompt_text':'actual'}}}])
    d = db.comparison_case_inputs('cn1',[run['id'],run['id']],['scope'])
    assert d['baseline']['prompt']['text'] == 'actual'
    assert d['baseline']['run_reference']['prompt']['source_type'] == 'run_example'
    assert d['baseline']['run_reference']['prompt']['example_case_id'] == 'cn2'
    with pytest.raises(ValueError): db.comparison_case_inputs('cn1',[run['id'],run['id']],['other'])
    with pytest.raises(ValueError): db.comparison_case_inputs('cn1',[run['id'],'missing'],['scope'])


def test_bounded_diff_and_json_order():
    js=Path('ra_triage_dashboard/static/js/run-comparison.js').read_text()
    script=js+'''
const assert=require('node:assert/strict');
assert.equal(comparisonDiffLines('中文\\n<|image_pad|>','中文\\n<|image_pad|>').every(r=>r.kind==='same'),true);
assert.equal(comparisonDiffLines('a\\nb','a\\nc')[1].kind,'change');
assert.equal(comparisonDiffLines('a','b')[0].kind,'change');
assert.equal(comparisonDiffLines('','')[0].kind,'same');
assert.equal(comparisonDiffLines('x'.repeat(200001),''),null);
assert.equal(comparisonDiffLines('a\\n'.repeat(2000),'b\\n'.repeat(2000)),null);
assert.equal(comparisonConfigText({b:1,a:{d:2,c:3}}),comparisonConfigText({a:{c:3,d:2},b:1}));
assert.notEqual(comparisonConfigText([1,2]),comparisonConfigText([2,1]));
'''
    subprocess.run(['node','-e',script],check=True,capture_output=True)


def test_nearest_trigger_frame_selection():
    js=Path('ra_triage_dashboard/static/js/detail-media.js').read_text()
    subprocess.run(['node','-e',js+"\nconst assert=require('node:assert/strict'); assert.equal(heroFrameIndex([{offset_ms:-9000},{offset_ms:0},{offset_ms:1000}]),1); assert.equal(heroFrameIndex([{offset_ms:-9000},{offset_ms:-5000},{offset_ms:1000}]),2); assert.equal(heroFrameIndex([{offset_sec:-2},{offset_sec:0}]),1);"],check=True,capture_output=True)
