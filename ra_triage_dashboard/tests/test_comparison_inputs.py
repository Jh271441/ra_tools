import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from ra_triage_dashboard.app.comparison_inputs import (
    case_input_projection,
    extra_input_matches,
    extra_input_summary,
    normalize_extra_input_filter,
)
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


def test_structured_extra_inputs_and_prompt_fallback():
    structured = extra_input_summary({}, {
        'routing_intents': ['straight'] * 7 + ['left_turn'] * 2,
        'lane_change_intents': {'no_lane_change': 6, 'lane_change': 3},
    })
    assert structured['axes']['routing']['counts'] == {'直行': 7, '左转': 2}
    assert structured['axes']['lane_change']['frame_count'] == 9
    prompt = extra_input_summary({}, {
        'prompt_text': 'Routing 意图：直行 7帧 左转 2帧\n自车变道意图：非变道 6帧 变道 3帧',
    })
    assert prompt['axes']['routing']['counts'] == {'直行': 7, '左转': 2}
    assert prompt['axes']['lane_change']['counts'] == {'非变道': 6, '变道': 3}

    probabilities = extra_input_summary({}, {'prompt_text': '\n'.join([
        't=-5.0s | 变道概率：保持车道=0.9674, 变更车道=0.0326 | Routing 概率：直行=0.9812, 左转=0.0057, 右转=0.0096, 掉头=0.0035',
        't=+5.0s | 变道概率：保持车道=0.0708, 变更车道=0.9292 | Routing 概率：直行=0.0719, 左转=0.0080, 右转=0.9157, 掉头=0.0044',
    ])})
    assert probabilities['axes']['routing']['counts'] == {'直行': 1, '右转': 1}
    assert probabilities['axes']['lane_change']['counts'] == {'非变道': 1, '变道': 1}


def test_extra_input_filter_requires_one_run_to_satisfy_complete_expression():
    summary = extra_input_summary({}, {
        'routing_intents': ['straight', 'u_turn'],
        'lane_change_intents': ['lane_change'],
    })
    filter_value = normalize_extra_input_filter({
        'version': 1, 'run': 'candidate', 'relation': 'all',
        'conditions': [
            {'axis': 'routing', 'operator': 'any', 'values': ['直行', '掉头']},
            {'axis': 'lane_change', 'operator': 'any', 'values': ['变道']},
        ],
    })
    assert extra_input_matches(summary, filter_value)
    assert not extra_input_matches({'available': False, 'axes': {}}, filter_value)


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
    single = db.comparison_case_inputs('cn1', ['', run['id']], ['scope'])
    assert single['baseline'] is None
    assert single['candidate']['prompt']['text'] == 'actual'
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


def test_single_run_selector_stays_actionable_without_coverage():
    js = Path('ra_triage_dashboard/static/js/run-comparison.js').read_text()
    script = js + '''
const assert=require('node:assert/strict');
const elements={
  comparisonLoadButton:{disabled:true}, comparisonSelectionNote:{textContent:''},
  comparisonBaselineRunPicker:{}, comparisonCandidateRunPicker:{},
};
globalThis.state={modelRuns:[{id:'run-a',baseline_prediction_count:0}],runComparison:{baselineRunId:'',candidateRunId:'run-a',loading:false}};
globalThis.$=(selector)=>elements[selector.slice(1)] || null;
globalThis.uiText=(zh)=>zh;
globalThis.populateUiSelect=()=>{};
globalThis.bindUiSelect=()=>{};
renderRunComparisonSelectors();
assert.equal(elements.comparisonLoadButton.disabled,false);
assert.match(elements.comparisonSelectionNote.textContent,/暂无输出/);
'''
    subprocess.run(['node', '-e', script], check=True, capture_output=True)


def test_nearest_trigger_frame_selection():
    js=Path('ra_triage_dashboard/static/js/detail-media.js').read_text()
    subprocess.run(['node','-e',js+"\nconst assert=require('node:assert/strict'); assert.equal(heroFrameIndex([{offset_ms:-9000},{offset_ms:0},{offset_ms:1000}]),1); assert.equal(heroFrameIndex([{offset_ms:-9000},{offset_ms:-5000},{offset_ms:1000}]),2); assert.equal(heroFrameIndex([{offset_sec:-2},{offset_sec:0}]),1); assert.equal(heroFrameIndex([{offset_ms:null,offset_sec:null},{offset_ms:1000}]),1); assert.ok(Number.isNaN(mediaFrameOffsetMs({offset_ms:null,offset_sec:null}))); "],check=True,capture_output=True)
