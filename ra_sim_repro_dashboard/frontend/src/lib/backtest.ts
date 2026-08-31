export interface PoststratifiedCounts {
  complete: boolean;
  precisionTp: number;
  precisionFp: number;
  recallTp: number;
  recallFn: number;
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
    return { complete: false, precisionTp: 0, precisionFp: 0, recallTp: 0, recallFn: 0 };
  }
  let precisionTp = 0;
  let precisionFp = 0;
  let recallTp = 0;
  let recallFn = 0;
  for (let index = 0; index < matrixRows.length; index += 1) {
    const matrix = matrixRows[index];
    if (!matrix) return { complete: false, precisionTp: 0, precisionFp: 0, recallTp: 0, recallFn: 0 };
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
    ) return { complete: false, precisionTp: 0, precisionFp: 0, recallTp: 0, recallFn: 0 };

    const source = sourceRows[index];
    const precisionAutoTp = optionalNumeric(
      source.precision_auto_tp ?? source.auto_trigger_tp,
    );
    const precisionAutoFp = optionalNumeric(
      source.precision_auto_fp ?? source.auto_trigger_fp,
    );
    const recallAutoTp = optionalNumeric(
      source.recall_auto_tp ?? source.auto_trigger_tp,
    );
    const recallManualFn = optionalNumeric(
      source.recall_manual_fn ?? source.manual_trigger_fn,
    );
    if (
      precisionAutoTp == null || precisionAutoTp < 0
      || precisionAutoFp == null || precisionAutoFp < 0
      || recallAutoTp == null || recallAutoTp < 0
      || recallManualFn == null || recallManualFn < 0
    ) return { complete: false, precisionTp: 0, precisionFp: 0, recallTp: 0, recallFn: 0 };
    precisionTp += (
      precisionAutoTp * positiveAutoRate
      + recallManualFn * positiveManualRate
    );
    precisionFp += precisionAutoFp * negativeAutoRate;
    recallTp += (
      recallAutoTp * positiveAutoRate
      + recallManualFn * positiveManualRate
    );
    recallFn += (
      recallAutoTp * (1 - positiveAutoRate)
      + recallManualFn * (1 - positiveManualRate)
    );
  }
  return { complete: true, precisionTp, precisionFp, recallTp, recallFn };
}
