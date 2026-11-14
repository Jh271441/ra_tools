import { test } from 'node:test';
import assert from 'node:assert/strict';
import { evaluationKpi, evaluationSummary } from '../src/lib/evaluationProjection.ts';

const revision = {context:{release:'gen4-release-20261016'}, source_count:2007, generated_at:'2026-11-05T00:00:00Z', metrics:{available:false,eligible:1816,covered:1751,coverage:1751/1816,road_matches:1234,online_precision:451/1486,online_recall:765/1095,precision:null,recall:null,sim_repro_rate:null,counts:{precision_numerator:451,precision_denominator:1486,recall_numerator:765,recall_denominator:1095},sim_counts:{precision_numerator:500,precision_denominator:1300,recall_numerator:700,recall_denominator:1000},cohorts:{positive_auto:{count:1095,matches:700}}}};

test('independent source numerators reach shared overview without a common TP substitution',()=>{
  const value=evaluationKpi(revision);
  assert.equal(value.source_gt.precision_numerator,451);
  assert.equal(value.source_gt.recall_numerator,765);
  assert.equal(value.source_gt.online_precision,451/1486);
  assert.equal(value.source_gt.online_recall,765/1095);
  assert.equal(evaluationSummary(revision).current.version_key,revision.context.release);
});

test('incomplete coverage preserves chart gaps and counts without publishing partial rates',()=>{
  const value=evaluationKpi(revision);
  for(const key of ['precision','recall','sim_repro_rate','positive_auto_repro_rate','f1']) assert.equal(value[key],null);
  assert.equal(value.evaluated_cases,1751);
  assert.equal(value.sim_estimate.same_version_projection.available,false);
  assert.equal(value.sim_estimate.precision_numerator,500);
});

test('covered display includes reproduction while full metrics remain unavailable',()=>{
  const value=structuredClone(revision);
  Object.assign(value.metrics,{covered_precision:500/1300,covered_recall:700/1000,covered_repro_rate:1234/1751,
    covered_source_counts:{precision_numerator:450,precision_denominator:1400,recall_numerator:750,recall_denominator:1000}});
  const kpi=evaluationKpi(value), scope=kpi.evaluation_scope;
  assert.equal(scope.complete,false);assert.equal(scope.covered,1751);assert.equal(scope.eligible,1816);
  assert.equal(scope.repro_rate,1234/1751);assert.equal(scope.precision,500/1300);assert.equal(scope.recall,.7);
  assert.equal(scope.road_precision,450/1400);assert.equal(scope.road_recall,.75);
  assert.equal(kpi.precision,null);assert.equal(kpi.sim_repro_rate,null);
  assert.equal(kpi.source_gt.online_precision,451/1486);
});

test('an old partial revision never substitutes full-population road values for a paired baseline',()=>{
  const scope=evaluationKpi(revision).evaluation_scope;
  assert.equal(scope.road_counts,null);assert.equal(scope.road_precision,null);assert.equal(scope.road_recall,null);
});

test('stale, empty and impossible covered scopes cannot publish observed chart rates',()=>{
  assert.equal(evaluationKpi(revision,true).evaluation_scope,undefined);
  for(const covered of [0,1817]) assert.equal(evaluationKpi({...revision,metrics:{...revision.metrics,covered}}).evaluation_scope,undefined);
});

test('a stale revision and an inconsistent available flag preserve counts but suppress full rates',()=>{
 const value=structuredClone(revision);
 Object.assign(value.metrics,{available:true,precision:.4,recall:.7,sim_repro_rate:.8});
 for(const kpi of [evaluationKpi(value),evaluationKpi({...value,metrics:{...value.metrics,covered:1816,coverage:1}},true)]){
  assert.equal(kpi.precision,null);assert.equal(kpi.recall,null);assert.equal(kpi.sim_repro_rate,null);
  assert.equal(kpi.quality_gate_passed,false);
  assert.equal(kpi.sim_estimate.same_version_projection.available,false);
  assert.equal(kpi.source_gt.precision_numerator,451);assert.equal(kpi.source_gt.recall_numerator,765);
 }
 Object.assign(value.metrics,{covered:1816,coverage:1});
 assert.equal(evaluationKpi(value).precision,.4);assert.equal(evaluationKpi(value).recall,.7);
});
