import assert from 'node:assert/strict';
import test from 'node:test';

import { poststratifyBacktestWindow } from '../src/lib/backtest.ts';

function cohort(expected, triggerRate) {
  return { expected, evaluated: expected, trigger_rate: triggerRate };
}

test('post-stratifies equal canary cohorts with online TP FP FN populations', () => {
  const result = poststratifyBacktestWindow([
    { auto_trigger_tp: 100, auto_trigger_fp: 20, manual_trigger_fn: 50 },
  ], [{
    expected: 30,
    evaluated: 30,
    dpe_coverage: 1,
    cohorts: {
      positive_auto: cohort(10, 0.8),
      negative_auto: cohort(10, 0.25),
      positive_manual: cohort(10, 0.6),
    },
  }]);

  assert.deepEqual(result, {
    complete: true,
    precisionTp: 110,
    precisionFp: 5,
    recallTp: 110,
    positiveAutoNotTriggered: 20,
    positiveManualNotTriggered: 20,
    negativeAutoNotTriggered: 15,
    businessRecallFn: 40,
    triggerReproFn: 55,
  });
  assert.equal(result.precisionTp / (result.precisionTp + result.precisionFp), 110 / 115);
  assert.equal(result.recallTp / (result.recallTp + result.businessRecallFn), 110 / 150);
  assert.equal(result.recallTp / (result.recallTp + result.triggerReproFn), 110 / 165);
});

test('keeps distinct Shuyi precision and recall numerators', () => {
  const result = poststratifyBacktestWindow([{
    precision_auto_tp: 80,
    precision_auto_fp: 20,
    recall_auto_tp: 100,
    recall_manual_fn: 50,
  }], [{
    expected: 30,
    evaluated: 30,
    dpe_coverage: 1,
    cohorts: {
      positive_auto: cohort(10, 0.8),
      negative_auto: cohort(10, 0.25),
      positive_manual: cohort(10, 0.6),
    },
  }]);

  assert.deepEqual(result, {
    complete: true,
    precisionTp: 94,
    precisionFp: 5,
    recallTp: 110,
    positiveAutoNotTriggered: 20,
    positiveManualNotTriggered: 20,
    negativeAutoNotTriggered: 15,
    businessRecallFn: 40,
    triggerReproFn: 55,
  });
});

test('rejects an incomplete cohort instead of drawing a partial curve', () => {
  const result = poststratifyBacktestWindow([
    { auto_trigger_tp: 100, auto_trigger_fp: 20, manual_trigger_fn: 50 },
  ], [{
    expected: 30,
    evaluated: 30,
    dpe_coverage: 1,
    cohorts: {
      positive_auto: cohort(10, 0.8),
      negative_auto: { expected: 10, evaluated: 9, trigger_rate: 0.2 },
      positive_manual: cohort(10, 0.6),
    },
  }]);

  assert.deepEqual(result, {
    complete: false,
    precisionTp: 0,
    precisionFp: 0,
    recallTp: 0,
    positiveAutoNotTriggered: 0,
    positiveManualNotTriggered: 0,
    negativeAutoNotTriggered: 0,
    businessRecallFn: 0,
    triggerReproFn: 0,
  });
});

test('rejects a cohort with no trigger rate', () => {
  const result = poststratifyBacktestWindow([
    { auto_trigger_tp: 100, auto_trigger_fp: 20, manual_trigger_fn: 50 },
  ], [{
    expected: 30,
    evaluated: 30,
    dpe_coverage: 1,
    cohorts: {
      positive_auto: cohort(10, 0.8),
      negative_auto: { expected: 10, evaluated: 10 },
      positive_manual: cohort(10, 0.6),
    },
  }]);

  assert.equal(result.complete, false);
  assert.equal(result.triggerReproFn, 0);
});

test('rejects missing online population counts instead of treating them as zero', () => {
  const result = poststratifyBacktestWindow([
    { auto_trigger_tp: 100, auto_trigger_fp: 20 },
  ], [{
    expected: 30,
    evaluated: 30,
    dpe_coverage: 1,
    cohorts: {
      positive_auto: cohort(10, 0.8),
      negative_auto: cohort(10, 0.25),
      positive_manual: cohort(10, 0.6),
    },
  }]);

  assert.equal(result.complete, false);
  assert.equal(result.triggerReproFn, 0);
});
