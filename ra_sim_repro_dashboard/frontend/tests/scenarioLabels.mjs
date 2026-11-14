import test from 'node:test';
import assert from 'node:assert/strict';
import { scenarioLabelsForIssue } from '../src/lib/scenarioLabels.ts';

test('scenario labels bind to both issue and scenario IDs despite broad search matches', () => {
  assert.deepEqual(scenarioLabelsForIssue('cn1',['10','11'],[
    {issue_id:'cn2',scenario_id:'10',scenario_labels:['other-issue']},
    {issue_id:'cn1',scenario_id:'99',scenario_labels:['other-scene']},
    {issue_id:'cn1',scenario_id:'10',scenario_labels:['actual-label']},
  ]),[{scenarioId:'10',labels:['actual-label']},{scenarioId:'11',labels:null}]);
});

test('missing or malformed label receipts never become a confirmed empty set', () => {
  assert.deepEqual(scenarioLabelsForIssue('cn1',['10','11','12'],[
    {issue_id:'cn1',scenario_id:'10'},
    {issue_id:'cn1',scenario_id:'11',scenario_labels:[null]},
    {issue_id:'cn1',scenario_id:'12',scenario_labels:[]},
  ]),[{scenarioId:'10',labels:null},{scenarioId:'11',labels:null},{scenarioId:'12',labels:[]}]);
});

test('conflicting scenario label receipts remain unknown', () => {
  assert.deepEqual(scenarioLabelsForIssue('cn1',['10'],[
    {issue_id:'cn1',scenario_id:'10',scenario_labels:['positive_auto']},
    {issue_id:'cn1',scenario_id:'10',scenario_labels:['negative_auto']},
  ]),[{scenarioId:'10',labels:null}]);
});

test('duplicate receipts and reordered label sets preserve exact platform values', () => {
  assert.deepEqual(scenarioLabelsForIssue('cn1',['10','10'],[
    {issue_id:'cn1',scenario_id:'10',scenario_labels:['ra_original_positive_auto',' custom ','','ra_original_positive_auto']},
    {issue_id:'cn1',scenario_id:'10',scenario_labels:['',' custom ','ra_original_positive_auto']},
  ]),[{scenarioId:'10',labels:['',' custom ','ra_original_positive_auto']}]);
});
