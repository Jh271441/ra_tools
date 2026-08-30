export interface PoststratifiedCounts {
  complete: boolean;
  tp: number;
  fp: number;
  fn: number;
}

function numeric(value: unknown) {
  if (typeof value === 'number') return value;
  if (typeof value === 'string' && value.trim()) return Number(value);
  return 0;
}

function optionalNumeric(value: unknown) {
  if (value == null || value === '') return undefined;
  const result = numeric(value);
  return Number.isFinite(result) ? result : undefined;
}

function cohortTriggerRate(row: Record<string, unknown>, cohortName: string) {
  const cohorts = row.cohorts;
  if (!cohorts || typeof cohorts !== 'object') return undefined;
  const cohort = (cohorts as Record<string, unknown>)[cohortName];
  if (!cohort || typeof cohort !== 'object') return undefined;
  const metrics = cohort as Record<string, unknown>;
  const expected = optionalNumeric(metrics.expected);
  const evaluated = optionalNumeric(metrics.evaluated);
  const triggerRate = optionalNumeric(metrics.trigger_rate);
  if (
    expected == null || expected <= 0 || evaluated !== expected || triggerRate == null
    || triggerRate < 0 || triggerRate > 1
  ) return undefined;
  return triggerRate;
}

export function poststratifyBacktestWindow(
  sourceRows: Array<Record<string, unknown>>,
  matrixRows: Array<Record<string, unknown> | undefined>,
): PoststratifiedCounts {
  if (!sourceRows.length || matrixRows.length !== sourceRows.length) {
    return { complete: false, tp: 0, fp: 0, fn: 0 };
  }
  let tp = 0;
  let fp = 0;
  let fn = 0;
  for (let index = 0; index < matrixRows.length; index += 1) {
    const matrix = matrixRows[index];
    if (!matrix) return { complete: false, tp: 0, fp: 0, fn: 0 };
    const expected = numeric(matrix.expected);
    const evaluated = numeric(matrix.evaluated);
    const dpeCoverage = numeric(matrix.dpe_coverage);
    const positiveAutoRate = cohortTriggerRate(matrix, 'positive_auto');
    const negativeAutoRate = cohortTriggerRate(matrix, 'negative_auto');
    const positiveManualRate = cohortTriggerRate(matrix, 'positive_manual');
    if (
      expected <= 0 || evaluated !== expected || dpeCoverage < 1
      || positiveAutoRate == null || negativeAutoRate == null
      || positiveManualRate == null
    ) return { complete: false, tp: 0, fp: 0, fn: 0 };

    const source = sourceRows[index];
    const autoTp = optionalNumeric(source.auto_trigger_tp);
    const autoFp = optionalNumeric(source.auto_trigger_fp);
    const manualFn = optionalNumeric(source.manual_trigger_fn);
    if (
      autoTp == null || autoTp < 0 || autoFp == null || autoFp < 0
      || manualFn == null || manualFn < 0
    ) return { complete: false, tp: 0, fp: 0, fn: 0 };
    tp += autoTp * positiveAutoRate + manualFn * positiveManualRate;
    fp += autoFp * negativeAutoRate;
    fn += autoTp * (1 - positiveAutoRate) + manualFn * (1 - positiveManualRate);
  }
  return { complete: true, tp, fp, fn };
}
