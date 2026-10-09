"""The reason diagram describes the server projection without overriding it."""
from pathlib import Path
import subprocess
import unittest


class CaseLabelExplanationTest(unittest.TestCase):
    def test_reason_states_follow_projection_and_preserve_inputs(self):
        source = (Path(__file__).resolve().parents[1] / 'static/js/case-label-explanation.js').read_text()
        script = source + r'''
const assert = require('node:assert/strict');
function uiText(zh, en) { return zh; }
const explain = label_state => caseLabelExplanation({label_state});
assert.equal(explain({state:'none',sources:[]}).reason,'暂无有效标注来源');
let pending={state:'pending',sources:[{task_id:'a',state:'pending',assigned_count:2,submitted_count:1}]};
const before=JSON.stringify(pending);
assert.equal(explain(pending).reason,'任务还缺 1 份提交');
assert.equal(JSON.stringify(pending),before);
assert.equal(explain({state:'pending',sources:[{task_id:'a',state:'pending',assigned_count:2,submitted_count:2}]}).reason,'仍有来源未形成有效结果');
const sources=[{task_id:'a',state:'resolved',expected_output:'误触发'},{task_id:'b',state:'resolved',expected_output:'正确触发'}];
assert.equal(explain({state:'conflict',sources}).reason,'不同来源的结果不一致');
assert.equal(explain({state:'conflict',sources}).next,'完成 Issue 裁决');
assert.equal(explain({state:'conflict',sources:[{task_id:'a',state:'conflict'}]}).next,'先完成任务内裁决');
assert.equal(explain({state:'stale',expected_output:'误触发',decision:{stale:true},sources}).output,'');
let resolved={state:'resolved',expected_output:'无需协助',decision:{id:9,stale:false},sources};
assert.equal(explain(resolved).output,'无需协助');
assert.equal(explain(resolved).reason,'有效 Issue 裁决生效');
assert.equal(explain({state:'resolved',expected_output:'误触发',sources:[{state:'resolved',method:'adjudication'}]}).reason,'有效任务内裁决生效');
assert.equal(explain({state:'resolved',expected_output:'误触发',sources:[{state:'resolved'},{state:'resolved'}]}).reason,'所有来源已完成且结果一致');
'''
        subprocess.run(['node', '-e', script], check=True, capture_output=True)
