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

  assert.deepEqual(result, { complete: true, tp: 110, fp: 5, fn: 40 });
  assert.equal(result.tp / (result.tp + result.fp), 110 / 115);
  assert.equal(result.tp / (result.tp + result.fn), 110 / 150);
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

  assert.deepEqual(result, { complete: false, tp: 0, fp: 0, fn: 0 });
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

  assert.deepEqual(result, { complete: false, tp: 0, fp: 0, fn: 0 });
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

  assert.deepEqual(result, { complete: false, tp: 0, fp: 0, fn: 0 });
});
