"""Behavior checks for shared components after extraction from work-split.js."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'static/js'


class AssignmentComponentTest(unittest.TestCase):
    def test_new_groups_start_full_and_equalize_suggestion_avoids_tab_hijack(self):
        source = (ROOT / 'allocation-groups.js').read_text()
        self.assertNotIn('onkeydown', source)
        self.assertNotIn('data-group-tab-suggest', source)
        self.assertIn('data-group-equalize', source)
        script = source + r'''
const assert = require('node:assert/strict');
const first = newAllocationGroup();
const second = newAllocationGroup([first]);
assert.equal(first.coverage_percent, 100);
assert.equal(second.coverage_percent, 100);
second.coverage_percent = 50;
const third = newAllocationGroup([first, second]);
assert.equal(third.coverage_percent, 100);
assert.equal(second.coverage_percent, 50);

// Header equalize suggestion activates when uneven or zero-share, clears once equalized
const uneven = [{name: 'jasperchen', review_percent: 0}, {name: 'liangxianghui', review_percent: 0},
  {name: 'yupuxue_v', review_percent: 50}, {name: 'zhangxuzhao_v', review_percent: 50}];
const hint = computeGroupEqualizeSuggestion(uneven);
assert.ok(hint);
assert.deepEqual(hint.shares, [25, 25, 25, 25]);
assert.match(hint.textZh, /可一键均分：每人 25%/);
completeGroupShares(uneven, true);
assert.equal(computeGroupEqualizeSuggestion(uneven), null);
'''
        subprocess.run(['node', '-e', script], check=True, capture_output=True)

    def test_manual_edit_and_new_request_win_over_old_name_response(self):
        script = (ROOT / 'assignment-naming.js').read_text() + r'''
const assert=require('node:assert/strict');
let queued, pending=[], requests=0;
const input={value:'',dataset:{}}, handlers={}, refresh={disabled:false,addEventListener:(name,cb)=>handlers.refresh=cb};
input.addEventListener=(name,cb)=>handlers.input=cb;
state={session:{is_admin:true}};
window={clearTimeout:()=>{},setTimeout:cb=>{queued=cb;return 1;}};
assignmentNameElements=()=>({input,refresh,status:{}});
assignmentNameContext=()=>({datasetLabels:['0508'],baselineIds:['0508'],caseCount:10,memberCount:1,reviewersPerIssue:1,overlapRatio:0,assignmentKind:'case_labeling',workflowMode:'',modelRunId:'',comparison:'all'});
renderAssignmentNameStatus=()=>{};
api=()=>{requests++;return new Promise(resolve=>pending.push(resolve));};
(async()=>{
 bindAssignmentNameInput('labeling');
 updateAssignmentNameSuggestion('labeling',{immediate:true});
 assert.match(input.value,/0508.*10 Case/);
 const first=queued();
 input.value='my manual name';handlers.input();
 pending.shift()({source:'llm',suggestion:'late model name'});await first;
 assert.equal(input.value,'my manual name');
 handlers.refresh();const second=queued();
 assert.equal(input.dataset.manualEdited,'false');
 pending.shift()({source:'llm',suggestion:'new model name'});await second;
 assert.equal(input.value,'new model name');
 updateAssignmentNameSuggestion('labeling');assert.equal(requests,2);
 handlers.refresh();const third=queued();pending.shift()({source:'rule',reason:'timeout'});await third;
 assert.equal(input.dataset.suggestionSource,'rule');assert.equal(input.dataset.suggestionReason,'timeout');
 assert.match(input.value,/0508.*10 Case/);assert.equal(requests,3);
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        subprocess.run(['node', '-e', script], check=True, capture_output=True)

    def test_group_shares_keep_zero_distinct_from_missing_input(self):
        script = (ROOT / 'allocation-groups.js').read_text() + r'''
const assert=require('node:assert/strict');
const input=value=>({value:String(value??''),valueAsNumber:value??NaN});
const people=[['alice',100],['bob',0],['carol',null]].map(([name,share])=>({
  querySelector:match=>match==='[data-group-member]'?{value:name}:input(share)
}));
const card={dataset:{setupGroup:'rd'},querySelector:match=>
  match==='[data-group-strategy]'?{value:'overlap'}:input(100),querySelectorAll:()=>people};
const root={querySelector:()=>null,querySelectorAll:match=>match==='[data-setup-group]'?[card]:[]};
const draft=readAllocationGroupSetup(root);
assert.deepEqual(draft.groups,[{group_id:'rd',coverage_percent:100,coverage_strategy:'overlap',
  members:[{name:'alice',review_percent:100},{name:'bob',review_percent:0},{name:'carol',review_percent:null}]}]);
apiResponseError=(zh,en)=>({messages:{zh,en}});
assert.ok(groupAllocationSetupError(draft));
draft.groups[0].members.pop();
assert.equal(groupAllocationSetupError(draft),null);
'''
        subprocess.run(['node', '-e', script], check=True, capture_output=True)

    def test_group_share_edit_fills_only_selected_peers_to_exactly_100(self):
        script = (ROOT / 'allocation-groups.js').read_text() + r'''
const assert = require('node:assert/strict');

function setup(values, selected = values.map(() => true)) {
  const fields = values.map((value) => ({
    value: String(value),
    get valueAsNumber() { return this.value === "" ? NaN : Number(this.value); },
    closest: () => card,
  }));
  const rows = fields.map((field, index) => ({
    querySelector: (selector) => selector === "[data-group-member]"
      ? {value: selected[index] ? "member-" + index : ""}
      : field,
  }));
  const card = {querySelectorAll: () => rows};
  return fields;
}

const values = (fields) => fields.map((field) => field.valueAsNumber);
const pair = setup([100, 0]);
pair[0].value = "62.35";
rebalanceGroupShare(pair[0]);
assert.deepEqual(values(pair), [62.35, 37.65]);

const triad = setup([25, 30, 45, 0], [true, true, true, false]);
triad[0].value = "100";
const edit = rebalanceGroupShare(triad[0]);
assert.deepEqual(values(triad), [100, 0, 0, 0]);
triad[0].value = "";
rebalanceGroupShare(triad[0], edit);
assert.deepEqual(values(triad).slice(1), [0, 0, 0]);
triad[0].value = "100.01";
rebalanceGroupShare(triad[0], edit);
assert.deepEqual(values(triad).slice(1), [0, 0, 0]);
triad[0].value = "33.33";
rebalanceGroupShare(triad[0], edit);
assert.deepEqual(values(triad), [33.33, 26.67, 40, 0]);
assert.deepEqual(values(pair), [62.35, 37.65]);

const zeros = setup([100, 0, 0, 0]);
zeros[0].value = "71";
rebalanceGroupShare(zeros[0]);
assert.deepEqual(values(zeros), [71, 9.67, 9.67, 9.66]);
assert.deepEqual(splitGroupShares(10000, [1, 1, 1]), [33.34, 33.33, 33.33]);
assert.equal(rebalanceGroupShare(setup([100])[0]), null);
'''
        subprocess.run(['node', '-e', script], check=True, capture_output=True)

    def test_task_allocation_editor_omits_duplicate_saved_details_and_places_delete_in_footer(self):
        source = (ROOT / 'task-allocation.js').read_text()
        self.assertNotIn('task-allocation-current', source)
        self.assertNotIn('Saved allocation details', source)
        self.assertIn('task-allocation-footer-start', source)
        self.assertIn('data-allocation-delete', source)

    def test_cross_pairing_scheme3_removes_matrix_and_supports_modes_and_per_group_slots(self):
        groups_src = (ROOT / 'allocation-groups.js').read_text()
        preview_src = (ROOT / 'allocation-group-preview.js').read_text()
        self.assertNotIn('renderAllocationCrossMatrix', preview_src)
        self.assertNotIn('allocation-matrix-table', preview_src)
        self.assertIn('data-pairing-mode', groups_src)
        self.assertIn('data-rule-group-member', groups_src)
        self.assertIn('allocation-rules-info', groups_src)
        self.assertIn('data-ui-info-align="end"', groups_src)
        self.assertIn('allocation-strategy-switch', groups_src)
        self.assertNotIn('<select data-group-strategy>', groups_src)
        self.assertIn('assignment-ratio-box', groups_src)
        self.assertIn('assignment-ratio-unit', groups_src)
        self.assertIn('allocation-add-icon', groups_src)
        self.assertIn('allocation-unit-switch', groups_src)
        self.assertIn('allocation-setup-surface', groups_src)
        script = groups_src + r'''
const assert = require('node:assert/strict');
global.uiText = (zh) => zh;
global.escapeHtml = (v) => String(v ?? '');

const twoByTwo = [
  {group_id: 'g1', members: [{name: 'jasperchen', review_percent: 50}, {name: 'liangxianghui', review_percent: 50}]},
  {group_id: 'g2', members: [{name: 'zhangxuzhao_v', review_percent: 50}, {name: 'yupuxue_v', review_percent: 50}]},
];
const chips = renderAllocationPairedChips(twoByTwo);
assert.ok(chips.includes('data-paired-preview'));
assert.equal((chips.match(/allocation-paired-chip"/g) || []).length, 2);
assert.match(chips, /jasperchen[\s\S]*↔[\s\S]*zhangxuzhao_v/);
assert.match(chips, /liangxianghui[\s\S]*↔[\s\S]*yupuxue_v/);

const oneByTwo = [
  {group_id: 'g1', members: [{name: 'jasperchen', review_percent: 0}, {name: 'liangxianghui', review_percent: 100}]},
  {group_id: 'g2', members: [{name: 'zhangxuzhao_v', review_percent: 75}, {name: 'yupuxue_v', review_percent: 25}]},
];
const unevenChips = renderAllocationPairedChips(oneByTwo);
assert.equal((unevenChips.match(/allocation-paired-chip"/g) || []).length, 2);
assert.ok(!unevenChips.includes('jasperchen'));
assert.ok(unevenChips.includes('zhangxuzhao_v'));
assert.ok(unevenChips.includes('yupuxue_v'));

// Exact count input mode math, conversion, rebalancing & equalize detection
assert.deepEqual(apportionIntegerCounts(117, [5000, 5000]), [59, 58]);
assert.equal(allocationGroupDenom(117, 117, 58, 'remaining'), 59);
assert.equal(allocationGroupDenom(117, 117, 58, 'total'), 117);
assert.equal(coveragePercentFromCount(117, 58), 49.57);
assert.equal(coverageCountFromPercent(117, 49.57), 58);

// Read count-mode DOM into exact 100%-summing percentages
const numField = (val, disabled = false) => ({
  value: String(val), valueAsNumber: Number(val), disabled,
});
const countRows = [['jasperchen', 40], ['liangxianghui', 77]].map(([name, cnt]) => ({
  querySelector: (sel) => sel === '[data-group-member]' ? {value: name} : numField(cnt),
}));
const countCard = {
  dataset: {setupGroup: 'g1', memberDenom: '117', groupCompleted: '0'},
  querySelector: (sel) => sel === '[data-group-field="coverage"]' ? numField(117, true) : null,
  querySelectorAll: () => countRows,
};
const countRoot = {
  dataset: {inputUnit: 'count', caseCount: '117', quotaBasis: 'total'},
  querySelector: () => null,
  querySelectorAll: (sel) => sel === '[data-setup-group]' ? [countCard] : [],
};
const countDraft = readAllocationGroupSetup(countRoot);
assert.equal(countDraft.inputUnit, 'count');
assert.equal(countDraft.groups[0].coverage_percent, 100);
assert.deepEqual(countDraft.groups[0].members, [
  {name: 'jasperchen', review_percent: 34.19},
  {name: 'liangxianghui', review_percent: 65.81},
]);
assert.deepEqual(apportionIntegerCounts(117, [3419, 6581]), [40, 77]);

// Rebalance peer counts cleanly in count mode
const fakeRoot = {dataset: {inputUnit: 'count'}};
const fakeFields = [59, 58].map((val) => ({
  value: String(val),
  get valueAsNumber() { return this.value === '' ? NaN : Number(this.value); },
  closest: () => fakeCard,
}));
const fakeRows = fakeFields.map((field, idx) => ({
  querySelector: (sel) => sel === '[data-group-member]' ? {value: 'u' + idx} : field,
}));
const fakeCard = {
  dataset: {memberDenom: '117'},
  closest: () => fakeRoot,
  querySelectorAll: () => fakeRows,
};
fakeFields[0].value = '40';
rebalanceGroupShare(fakeFields[0]);
assert.deepEqual(fakeFields.map((f) => Number(f.value)), [40, 77]);

// Equalize suggestion in count mode
assert.equal(computeGroupEqualizeSuggestion([{name: 'a', review_percent: 59}, {name: 'b', review_percent: 58}], {unit: 'count', denom: 117}), null);
const countEq = computeGroupEqualizeSuggestion([{name: 'a', review_percent: 40}, {name: 'b', review_percent: 77}], {unit: 'count', denom: 117});
assert.ok(countEq);
assert.deepEqual(countEq.shares, [59, 58]);
'''
        subprocess.run(['node', '-e', script], check=True, capture_output=True)

