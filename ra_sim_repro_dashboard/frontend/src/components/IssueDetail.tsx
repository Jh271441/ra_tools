import { useEffect, useMemo, useState } from 'react';
import { ExternalLink, GitBranch, RadioTower, Tags } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';
import type { IssueDetailResponse, ScenarioDetailResponse, ScenarioResult, SelectedIssueResult } from '../types';
import { Badge } from './ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';

interface IssueDetailProps {
  selected: SelectedIssueResult | null;
}

const panelClass = 'min-w-0 xl:sticky xl:top-24 xl:max-h-[calc(100vh-7rem)] xl:overflow-auto';

function labelVariant(label: string): 'success' | 'warning' | 'destructive' | 'outline' {
  if (label === 'TP') return 'success';
  if (label === 'FP') return 'destructive';
  if (label === 'FN') return 'warning';
  return 'outline';
}

function valueText(value: unknown) {
  if (value == null || value === '') return '-';
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(3);
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
}

function arrayValue(value: unknown): string[] {
  if (!value) return [];
  if (Array.isArray(value)) return value.map(String).filter(Boolean);
  return [String(value)];
}

function issueTime(value: unknown) {
  if (typeof value === 'number' && value > 1000000000000) {
    return new Date(value).toLocaleString();
  }
  if (typeof value === 'string' && /^\d{13}$/.test(value)) {
    return new Date(Number(value)).toLocaleString();
  }
  return valueText(value);
}

function field(raw: Record<string, unknown>, key: string) {
  return raw[key] ?? '-';
}

function MetricRow({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border/50 py-2 last:border-b-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="max-w-[62%] truncate text-right font-mono text-xs text-foreground" title={valueText(value)}>
        {valueText(value)}
      </span>
    </div>
  );
}

function ResultSummary({ result }: { result: ScenarioResult }) {
  const { t } = useTranslation();
  const raw = result.raw_metrics || {};
  return (
    <div className="metric-surface min-w-0 rounded-lg border p-3">
      <div className="mb-3 flex min-w-0 flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <GitBranch className="h-4 w-4 shrink-0 text-primary" />
          <span className="truncate text-sm font-semibold">{result.version_key}</span>
        </div>
        <Badge variant={labelVariant(result.precision_label)}>{result.precision_label}</Badge>
      </div>
      <div className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
        <div className="min-w-0 rounded-md border border-border/60 bg-background/45 px-3">
          <MetricRow label={t('roadSignal')} value={result.road_triggered ? t('roadTriggered') : t('roadNotTriggered')} />
          <MetricRow label={t('simSignal')} value={result.sim_triggered ? t('simTriggered') : t('simNotTriggered')} />
          <MetricRow label={t('triggerMetric')} value={field(raw, 'dpe_assist_channel_triggered')} />
          <MetricRow label={t('job')} value={field(raw, 'job_id')} />
        </div>
        <div className="min-w-0 rounded-md border border-border/60 bg-background/45 px-3">
          <MetricRow label={t('datasetRole')} value={field(raw, 'dataset_role')} />
          <MetricRow label={t('dataSource')} value={field(raw, 'data_source')} />
          <MetricRow label={t('triggerType')} value={result.trigger_type} />
          <MetricRow label={t('rootCause')} value={result.root_cause} />
        </div>
      </div>
      <div className="mt-3 min-w-0 rounded-md border border-border/60 bg-muted/35 px-3">
        <MetricRow label={t('modelScore')} value={result.model_score_max} />
        <MetricRow label={t('threshold')} value={result.threshold} />
        <MetricRow label={t('unstuckStatus')} value={result.unstuck_status} />
      </div>
    </div>
  );
}

export function IssueDetail({ selected }: IssueDetailProps) {
  const { t } = useTranslation();
  const [scenarioData, setScenarioData] = useState<ScenarioDetailResponse | null>(null);
  const [issueData, setIssueData] = useState<IssueDetailResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    if (!selected) {
      setScenarioData(null);
      setIssueData(null);
      setError('');
      return undefined;
    }
    setLoading(true);
    setError('');
    void Promise.all([
      api.scenarioDetail(selected.scenario_id),
      selected.issue_id ? api.issueDetail(selected.issue_id).catch(() => null) : Promise.resolve(null),
    ])
      .then(([scenarioResult, issueResult]) => {
        if (cancelled) return;
        setScenarioData(scenarioResult);
        setIssueData(issueResult);
      })
      .catch((err) => {
        if (cancelled) return;
        setScenarioData(null);
        setIssueData(null);
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const selectedResult = useMemo(() => {
    if (!scenarioData || !selected) return null;
    return (
      scenarioData.results.find((item) => item.version_key === selected.version_key) ||
      scenarioData.results[0] ||
      null
    );
  }, [scenarioData, selected]);

  const sourceLabels = useMemo(() => {
    const raw = selectedResult?.raw_metrics || {};
    return arrayValue(raw.source_labels);
  }, [selectedResult]);

  if (!selected) {
    return (
      <Card className={panelClass}>
        <CardHeader>
          <CardTitle>{t('issueDetail')}</CardTitle>
        </CardHeader>
        <CardContent className="flex min-h-[220px] items-center justify-center text-center text-sm text-muted-foreground">
          {t('noIssueSelected')}
        </CardContent>
      </Card>
    );
  }

  if (loading && !scenarioData) {
    return (
      <Card className={panelClass}>
        <CardHeader>
          <CardTitle>{t('issueDetail')}</CardTitle>
        </CardHeader>
        <CardContent className="flex min-h-[220px] items-center justify-center text-sm text-muted-foreground">{t('loading')}</CardContent>
      </Card>
    );
  }

  if (error || !scenarioData || !selectedResult) {
    return (
      <Card className={panelClass}>
        <CardHeader>
          <CardTitle>{t('issueDetail')}</CardTitle>
        </CardHeader>
        <CardContent className="min-h-[220px] text-sm text-destructive">
          {error || t('noScenarioDetail')}
        </CardContent>
      </Card>
    );
  }

  const issue = issueData?.issue || {};
  const scenario = scenarioData.scenario || {};
  const issueId = String(issue.issue_id || selected.issue_id || '');
  const title = String(issue.issue_topic || scenario.scenario_name || issueId || selected.scenario_id);
  const issueUrl = String(issue.url || (issueId ? `https://voyager.intra.xiaojukeji.com/paladin/issue/detail/${issueId}` : ''));

  return (
    <Card className={panelClass}>
      <CardHeader className="border-b border-border/70">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="break-words text-[15px] leading-6">{title}</CardTitle>
            <div className="mt-2 flex flex-wrap gap-2">
              {issueId ? <Badge variant="secondary">{issueId}</Badge> : null}
              <Badge variant="outline">{selected.scenario_id}</Badge>
              <Badge variant={labelVariant(selectedResult.precision_label)}>{selectedResult.precision_label}</Badge>
              {issue.issue_time ? <Badge variant="outline">{issueTime(issue.issue_time)}</Badge> : null}
            </div>
          </div>
          {issueUrl ? (
            <a className="inline-flex items-center gap-1 text-sm font-medium text-primary" href={issueUrl} target="_blank" rel="noreferrer">
              {t('open')}
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="grid min-w-0 gap-4 overflow-hidden">
        <div className="min-w-0">
          <div className="mb-2 flex items-center gap-2 text-[13px] font-semibold leading-5">
            <RadioTower className="h-4 w-4 text-primary" />
            {t('selectedResult')}
          </div>
          <ResultSummary result={selectedResult} />
        </div>

        <div className="min-w-0 overflow-hidden rounded-lg border border-border/70 bg-accent/15 p-3 dark:bg-white/[0.02]">
          <div className="mb-2 text-[13px] font-semibold leading-5">{t('selectedScenario')}</div>
          <div className="truncate font-mono text-xs">{selected.scenario_id}</div>
          <div className="mt-1 break-words text-xs text-muted-foreground">
            {String(scenario.scenario_name || '')}
          </div>
        </div>

        {sourceLabels.length ? (
          <div className="min-w-0 overflow-hidden rounded-lg border border-border/70 p-3">
            <div className="mb-2 flex items-center gap-2 text-[13px] font-semibold leading-5">
              <Tags className="h-4 w-4 text-primary" />
              {t('sourceLabels')}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {sourceLabels.map((label) => (
                <Badge key={label} variant="outline" className="max-w-full break-all font-mono text-[11px]">
                  {label}
                </Badge>
              ))}
            </div>
          </div>
        ) : null}

        {scenarioData.results.length > 1 ? (
          <div className="min-w-0 overflow-hidden rounded-lg border border-border/70 p-3">
            <div className="mb-2 text-[13px] font-semibold leading-5">{t('otherVersions')}</div>
            <div className="grid gap-2">
              {scenarioData.results.map((result) => (
                <div key={result.version_key} className="flex items-center justify-between gap-3 rounded-md bg-muted/35 px-3 py-2">
                  <span className="truncate font-mono text-xs">{result.version_key}</span>
                  <div className="flex shrink-0 items-center gap-2">
                    <Badge variant={labelVariant(result.precision_label)}>{result.precision_label}</Badge>
                    <span className="font-mono text-xs text-muted-foreground">
                      {result.sim_triggered ? t('simTriggered') : t('simNotTriggered')}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {issueData?.scenarios?.length ? (
          <div className="min-w-0 overflow-hidden rounded-lg border border-border/70 p-3">
            <div className="mb-2 text-[13px] font-semibold leading-5">
              {t('sameIssueScenarios')} ({issueData.scenarios.length})
            </div>
            <div className="grid max-h-56 gap-2 overflow-auto pr-1">
              {issueData.scenarios.slice(0, 12).map((entry) => (
                <div key={String(entry.scenario.scenario_id)} className="rounded-md bg-muted/35 px-3 py-2">
                  <div className="font-mono text-xs">{String(entry.scenario.scenario_id)}</div>
                  <div className="mt-1 truncate text-xs text-muted-foreground">
                    {String(entry.scenario.scenario_name || '')}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
