import { completeMetrics } from './evaluationFlow.ts';
import type { EvaluationRevision } from '../types/evaluation';
import type { KpiSummary, SummaryResponse } from '../types';

export function evaluationKpi(revision: EvaluationRevision, stale = false): KpiSummary {
  const m = revision.metrics,
    c = m.counts,
    s = m.sim_counts;
  const available = completeMetrics(m, stale);
  const paired = m.covered_source_counts || (available ? c : null);
  const ratio = (counts: Record<string, number> | null, metric: string) =>
    counts && counts[`${metric}_denominator`] > 0
      ? counts[`${metric}_numerator`] / counts[`${metric}_denominator`]
      : null;
  const covered = !stale && Number.isInteger(m.covered) && m.covered > 0 && m.covered <= m.eligible;
  const rate = (key: string) => {
    const group = m.cohorts[key],
      denominator = group?.evaluated ?? group?.count;
    return available && denominator ? group.matches / denominator : null;
  };
  return {
    reproduction: stale ? undefined : m.reproduction,
    evaluation_scope: covered
      ? {
          complete: available,
          covered: m.covered,
          eligible: m.eligible,
          precision: m.covered_precision,
          recall: m.covered_recall,
          repro_rate: m.covered_repro_rate,
          road_precision: ratio(paired, 'precision'),
          road_recall: ratio(paired, 'recall'),
          road_counts: paired,
          sim_counts: s,
        }
      : undefined,
    version_key: revision.context.release,
    label: revision.context.release,
    total_cases: revision.source_count,
    road_positive_cases: m.eligible,
    sim_positive_cases: s.precision_denominator,
    reproduced_cases: m.road_matches || 0,
    sim_repro_rate: available ? m.sim_repro_rate : null,
    model_repro_rate: null,
    fn_fallback_rate: null,
    fp_suppress_rate: null,
    precision: available ? m.precision : null,
    recall: available ? m.recall : null,
    f1: null,
    specificity: null,
    accuracy: null,
    positive_auto_repro_rate: rate('positive_auto'),
    negative_auto_repro_rate: rate('negative_auto'),
    positive_manual_repro_rate: rate('positive_manual'),
    evaluated_cases: m.covered,
    dpe_coverage: m.coverage || 0,
    quality_gate_passed: available,
    root_causes: {},
    source_gt: {
      online_precision: m.online_precision,
      online_recall: m.online_recall,
      auto_trigger_tp: c.precision_numerator,
      auto_trigger_fp: c.precision_denominator - c.precision_numerator,
      manual_trigger_fn: c.recall_denominator - c.recall_numerator,
      calculated_precision: m.online_precision,
      calculated_recall: m.online_recall,
      precision_numerator: c.precision_numerator,
      precision_denominator: c.precision_denominator,
      recall_numerator: c.recall_numerator,
      recall_denominator: c.recall_denominator,
      source: 'Shuyi',
      case_count: revision.source_count,
    },
    sim_estimate: {
      tp: s.precision_numerator,
      fp: s.precision_denominator - s.precision_numerator,
      fn: s.recall_denominator - s.recall_numerator,
      precision_numerator: s.precision_numerator,
      precision_denominator: s.precision_denominator,
      recall_numerator: s.recall_numerator,
      recall_denominator: s.recall_denominator,
      same_version_projection: {
        available,
        sim_precision: available ? m.precision : null,
        sim_business_recall: available ? m.recall : null,
        population_coverage: m.coverage,
        precision_gap:
          !available || m.precision == null || m.online_precision == null
            ? null
            : m.precision - m.online_precision,
        business_recall_gap:
          !available || m.recall == null || m.online_recall == null
            ? null
            : m.recall - m.online_recall,
        reason: available ? '' : 'coverage_pending',
      },
    },
  };
}
export function evaluationSummary(revision: EvaluationRevision, stale = false): SummaryResponse {
  const current = evaluationKpi(revision, stale);
  return {
    current,
    business_metrics: current,
    business_current_version: revision.context.release,
    previous: null,
    deltas: {},
    generated_at: revision.generated_at,
  };
}
