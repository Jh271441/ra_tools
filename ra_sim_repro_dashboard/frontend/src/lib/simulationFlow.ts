import type { BoardData } from '../components/ReleaseWorkflow';

export type StageId = 'collect' | 'prepare' | 'execute' | 'verify' | 'publish';
export type StageState = 'complete' | 'active' | 'warning' | 'blocked' | 'waiting' | 'unknown' | 'archived';
export const ANOMALY_CODES = ['label_changed', 'trigger_type_changed', 'issue_time_changed', 'road_version_changed', 'issues_added', 'issues_removed', 'collection_change_unresolved', 'missing_bag', 'preparation_failed', 'preparation_timeout', 'execution_failed', 'execution_cancelled', 'execution_unknown', 'results_missing', 'results_conflict', 'results_excluded', 'gate_blocked', 'submission_uncertain', 'preflight_failed', 'source_unavailable', 'progress_unavailable'] as const;
export type AnomalyCode = typeof ANOMALY_CODES[number];
export interface FlowAnomaly {
  resolved?: boolean; resolved_at?: string;
  code: AnomalyCode; count?: number | null; job_id?: number | null; observed_at?: string;
  items: { issue_id?: string; scenario_id?: string; field?: string; before?: unknown; after?: unknown; reason?: string }[];
}
export interface FlowStage {
  id: StageId;
  state: StageState;
  detail: string;
  count?: number | null;
  total?: number | null;
  progress?: number;
  exceptionCount?: number;
  resolvedLabelCount?: number;
  anomalies?: FlowAnomaly[];
}

/** The same edge activity model is shared by desktop and mobile. */
export function stageMotion(source: FlowStage, target: FlowStage, stale = false) {
  if (stale || [source.state, target.state].some(s => ['blocked', 'unknown', 'archived'].includes(s))) return {animated:false, scheduled:false};
  return {animated:source.state === 'active' || target.state === 'active',
    scheduled:[source.state, target.state].every(s => ['complete', 'warning'].includes(s))};
}

/** A projection of observed receipts. This must never decide whether to submit or publish. */
export function simulationFlow(data: BoardData, stale = false) {
  const s = data.selected;
  const evaluation = s.evaluation;
  const publication = s.metrics.publication || evaluation?.publication;
  const activeStates = ['queued', 'submitting', 'running', 'verifying', 'submission_uncertain'];
  const mainJobs = s.jobs.filter(j=>!j.backfill);
  const activeJob = mainJobs.find(j => j.progress ? ['RUNNING', 'STARTING'].includes(j.progress.state) : activeStates.includes(j.status));
  const job = activeJob || mainJobs.find(j => j.job_id === (publication?.primary_job_id || evaluation?.primary_job_id)) || mainJobs[0];
  const p = job?.progress;
  const archived = s.kind === 'archived' || Boolean(s.metrics.archived);
  const stages: FlowStage[] = [
    { id: 'collect', state: s.period?.status === 'running' ? 'active' : s.population_complete ? 'complete' : archived ? 'unknown' : 'waiting', detail: s.period?.status === 'running' ? 'collecting' : s.population_complete ? 'collected' : archived ? 'historyMissing' : 'awaitCollection', count: s.issue_count },
    { id: 'prepare', state: 'waiting', detail: 'awaitPreparation', count: s.scenario_count },
    { id: 'execute', state: 'waiting', detail: 'awaitExecution' },
    { id: 'verify', state: 'waiting', detail: 'awaitVerification' },
    { id: 'publish', state: 'waiting', detail: 'awaitPublication' },
  ];
  const [collect, prepare, execute, verify, publish] = stages;
  const collection = s.collection;
  const collectionAnomalies = s.collection_anomalies?.length ? s.collection_anomalies : collection?.population_changed_after_submission ? [{code:'collection_change_unresolved' as const,items:[]}] : [];
  const pendingCollection = collectionAnomalies.filter(a => !a.resolved);
  collect.resolvedLabelCount = collectionAnomalies.filter(a => a.resolved && a.code === 'label_changed').reduce((sum,a) => sum + (a.count || 0), 0);
  if (collection?.monitor_status) {
    collect.count = collection.auto_count;
    if (stale || collection.stale || collection.monitor_status === 'source_error') {
      collect.state = 'unknown'; collect.detail = 'collectionStale';
    } else if (pendingCollection.length) {
      collect.state = 'warning'; collect.detail = 'collectionChanged';
    } else if (collection.collection_status === 'stable') {
      collect.state = 'complete'; collect.detail = 'collectionStable';
    } else {
      collect.state = 'active'; collect.detail = 'collectionWatching';
    }
  }
  if (archived) {
    prepare.state = 'unknown'; prepare.detail = 'historyMissing';
    execute.state = 'unknown'; execute.detail = 'historyMissing';
  } else if (job?.status === 'preflight_failed' || job?.status === 'cancelled_stale') {
    prepare.state = 'blocked'; prepare.detail = 'preflightBlocked';
  } else if (job?.job_id || evaluation) {
    prepare.state = 'complete'; prepare.detail = 'prepared';
    prepare.count = job?.scenario_count ?? evaluation?.scenario_count;
  } else if (collect.state === 'complete' && s.is_current && data.current_status === 'ready') {
    prepare.detail = 'previewRequired';
  }
  if (!job && collection?.monitor_status === 'preparing_scenes') {
    prepare.state = 'active'; prepare.detail = 'scenesPreparing';
  } else if (!job && collection?.monitor_status === 'blocked') {
    const retry = collection.monitor_error_code === 'driver_timeout' && collection.monitor_error_action === 'prepare_scenes';
    prepare.state = retry ? 'warning' : 'blocked'; prepare.detail = retry ? 'scenesTimeout' : collection.monitor_error_code === 'scene_preparation_failed' ? 'scenesFailed' : 'collectionBlocked';
  }
  if (s.issue_tolerance?.abnormal_issue_count && prepare.state === 'complete') {
    prepare.state = 'warning'; prepare.detail = 'preparedWithExceptions';
    prepare.exceptionCount = s.issue_tolerance.abnormal_issue_count;
  }
  if (job) {
    if (p && p.total > 0 && Number.isFinite(p.total) && Number.isFinite(p.finished) && p.finished >= 0 && p.finished <= p.total) {
      execute.count = p.finished; execute.total = p.total; execute.progress = p.finished / p.total;
      execute.exceptionCount = p.failed + p.cancelled;
    }
    const ended = p?.state === 'COMPLETED';
    if (job.status === 'submission_uncertain') {
      execute.state = 'blocked'; execute.detail = 'uncertain';
    } else if (p?.state === 'CANCELLED' || ['cancelled', 'cancelled_stale', 'failed', 'preflight_failed'].includes(job.status)) {
      execute.state = 'blocked'; execute.detail = 'executionStopped';
    } else if (ended) {
      execute.state = p.failed + p.cancelled + p.unknown > 0 ? 'warning' : 'complete'; execute.detail = 'executionEnded';
    } else if (p && ['RUNNING', 'STARTING'].includes(p.state)) {
      execute.state = 'active'; execute.detail = 'executing';
    } else if (['queued', 'submitting'].includes(job.status)) {
      execute.state = 'active'; execute.detail = 'queued';
    } else {
      execute.state = 'unknown'; execute.detail = 'progressMissing';
    }
    if (job.progress_error || stale) { execute.state = 'unknown'; execute.detail = 'staleProgress'; }
  }
  if (evaluation) {
    verify.count = evaluation.valid_scenario_count; verify.total = evaluation.scenario_count;
    if (evaluation.scenario_count > 0 && evaluation.valid_scenario_count >= 0 && evaluation.valid_scenario_count <= evaluation.scenario_count) verify.progress = evaluation.valid_scenario_count / evaluation.scenario_count;
    verify.exceptionCount = evaluation.missing_scenario_count;
    verify.state = publication ? (publication.excluded_scenario_ids.length ? 'warning' : 'complete') : evaluation.quality_gate_passed ? 'complete' : 'blocked';
    verify.detail = publication ? 'verifiedPublished' : evaluation.quality_gate_passed ? 'verified' : 'gateBlocked';
  } else if (job?.status === 'verifying') {
    verify.state = 'active'; verify.detail = 'verifying';
  } else if (archived) { verify.state = 'unknown'; verify.detail = 'historyMissing'; }
  if (publication) {
    publish.state = 'complete'; publish.detail = 'published';
    publish.count = publication.valid_scenario_count; publish.total = publication.scenario_count;
  } else if (s.metrics.archived && s.metrics.available) {
    publish.state = 'archived'; publish.detail = 'archived';
  } else if (s.metrics.available && s.metrics.quality_gate_passed) {
    publish.state = 'complete'; publish.detail = 'accepted';
  } else if (evaluation && !evaluation.quality_gate_passed) {
    publish.state = 'blocked'; publish.detail = 'publicationBlocked';
  }
  const add = (target: FlowStage, code: AnomalyCode, count?: number | null, items: FlowAnomaly['items'] = []) => {
    if (count === 0) return;
    (target.anomalies ||= []).push({code, count, items: items.slice(0, 30)});
  };
  if (collectionAnomalies.length) collect.anomalies = [...collectionAnomalies];
  if (collect.detail === 'collectionStale') add(collect, 'source_unavailable');
  const prepFailures = s.issue_tolerance?.preparation_failures || collection?.preparation?.failures || [];
  for (const code of ['missing_bag','preparation_failed'] as const) {
    const rows = prepFailures.filter(f => (f.reason === 'missing_bag') === (code === 'missing_bag'));
    if (rows.length) add(prepare, code, new Set(rows.map(f => f.issue_id)).size, rows);
  }
  if (prepare.detail === 'preparedWithExceptions' && !prepFailures.length) add(prepare, 'preparation_failed', s.issue_tolerance?.abnormal_issue_count);
  if (prepare.detail === 'scenesTimeout') add(prepare, 'preparation_timeout');
  if (['scenesFailed','collectionBlocked'].includes(prepare.detail) && !prepFailures.length) add(prepare, 'preparation_failed');
  if (prepare.detail === 'preflightBlocked') add(prepare, 'preflight_failed');
  if (p) {
    add(execute, 'execution_failed', p.failed, (p.failures || []).filter(f=>f.status === 'FAILED'));
    add(execute, 'execution_cancelled', p.cancelled, (p.failures || []).filter(f=>f.status === 'CANCELLED'));
    add(execute, 'execution_unknown', p.unknown);
  }
  if (execute.detail === 'uncertain') add(execute, 'submission_uncertain');
  if (execute.detail === 'staleProgress') add(execute, 'progress_unavailable');
  if (execute.detail === 'executionStopped' && !execute.anomalies?.length) add(execute, job?.status === 'preflight_failed' ? 'preflight_failed' : p?.state === 'CANCELLED' ? 'execution_cancelled' : 'execution_failed');
  if (evaluation) {
    add(verify, 'results_missing', evaluation.missing_scenario_count, (evaluation.failures || []).map(f=>({issue_id:f.issue_id,scenario_id:f.scenario_id,reason:f.outcome_detail || f.outcome})));
    add(verify, 'results_conflict', evaluation.comparison.conflicts.length, evaluation.comparison.conflicts.map(scenario_id=>({scenario_id})));
    if (publication?.excluded_scenario_ids.length) add(verify, 'results_excluded', publication.excluded_scenario_ids.length, publication.excluded_scenario_ids.map(scenario_id=>({scenario_id})));
    if (!evaluation.quality_gate_passed && !publication) {
      if (!verify.anomalies?.length) add(verify, 'gate_blocked');
      add(publish, 'gate_blocked');
    }
  }
  // Current run observations and a retained publication may refer to different jobs.
  const retained = Boolean(publication && job?.job_id && publication.primary_job_id !== job.job_id);
  const defaultStage = stages.find(v => v.state === 'active' || v.state === 'blocked')?.id || (['complete', 'archived'].includes(publish.state) ? 'publish' : stages.find(v => v.state !== 'complete')?.id || 'collect');
  return { stages, job, publication, retained, defaultStage };
}

/** Last-Issue age from the latest successful server check; client animation never authorizes submission. */
export function collectionProgress(data: BoardData, stale = false) {
  const c = data.selected.collection;
  if (!c?.monitor_status) return null;
  const required = Math.max(1, c.quiet_seconds_required || 86400);
  const fresh = !stale && !c.stale && c.monitor_status !== 'source_error';
  const seconds = fresh ? Math.max(0, Math.min(required, c.quiet_seconds || 0)) : 0;
  const submitted = data.selected.jobs.length > 0;
  const ready = fresh && seconds >= required;
  const blocked = c.monitor_status === 'blocked' || Boolean(c.population_changed_after_submission);
  const retry = c.monitor_error_code === 'driver_timeout' && c.monitor_error_action === 'prepare_scenes';
  const status = submitted ? 'collectionSubmitted' : !fresh ? 'collectionPaused' : c.monitor_status === 'preparing_scenes' ? 'preparingScenes' : retry ? 'sceneRetry' : c.monitor_error_code === 'scene_preparation_failed' ? 'sceneBlocked' : blocked ? 'collectionNeedsReview' : data.mode !== 'auto' ? 'collectionManual' : !data.driver_ready || !data.scheduler_enabled ? 'collectionUnavailable' : ready ? 'collectionPreparing' : 'collectionAuto';
  return { seconds, required, progress: seconds / required, fresh, ready, status };
}

export function executionSeconds(start?: string | null, end?: string | null): number | null {
  if (!start || !end) return null;
  const elapsed = (Date.parse(end) - Date.parse(start)) / 1000;
  return Number.isFinite(elapsed) && elapsed >= 0 ? Math.floor(elapsed) : null;
}

/** Elapsed time since the last issue is informational, never collection eligibility. */
export function issueAge(timestamp: string | null | undefined, now: number) {
  if (!timestamp || !Number.isFinite(now)) return null;
  const elapsed = (now - Date.parse(timestamp)) / 1000;
  if (!Number.isFinite(elapsed) || elapsed < 0) return null;
  const seconds = Math.floor(elapsed);
  return { days: Math.floor(seconds / 86400), hours: Math.floor(seconds % 86400 / 3600), minutes: Math.floor(seconds % 3600 / 60), seconds: seconds % 60 };
}
