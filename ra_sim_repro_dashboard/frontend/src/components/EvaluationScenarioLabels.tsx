import { useEffect, useState } from 'react';
import { ExternalLink, RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { evaluationRequest } from '../api/evaluation';
import { scenarioLabelsForIssue, type ScenarioLabelRow } from '../lib/scenarioLabels';
import type { EvaluationContext, EvaluationIssue } from '../types/evaluation';
import { Badge } from './ui/badge';
import { Button } from './ui/button';

type LabelReceipt = {
  status: string;
  namespace?: string;
  checked_at?: string;
  items: (ScenarioLabelRow & { autotriage_labels: string[] })[];
};
const cache = new Map<string, { savedAt: number; receipt: LabelReceipt }>();

export function EvaluationScenarioLabels({
  issue,
  context,
  revision,
  label,
}: {
  issue: EvaluationIssue;
  context: EvaluationContext;
  revision?: string;
  label: (value: string | null) => string;
}) {
  const { t } = useTranslation();
  const [attempt, setAttempt] = useState(0),
    [receipt, setReceipt] = useState<LabelReceipt | null>(null);
  const [loading, setLoading] = useState(false),
    [failed, setFailed] = useState(false);
  const scope = JSON.stringify([context, revision, issue.issue_id, issue.scenario_ids]);
  useEffect(() => {
    if (!issue.scenario_ids.length || !issue.eligible) return;
    let active = true;
    const saved = cache.get(scope);
    if (!attempt && saved && Date.now() - saved.savedAt < 300_000) {
      setReceipt(saved.receipt);
      return;
    }
    setReceipt(null);
    setLoading(true);
    setFailed(false);
    const query = new URLSearchParams(
      Object.entries(context).filter(([, v]) => v) as [string, string][],
    );
    query.set('issue_id', issue.issue_id);
    void evaluationRequest<LabelReceipt>(`/scenario-labels?${query}`)
      .then((value) => {
        if (!active) return;
        cache.delete(scope);
        cache.set(scope, { savedAt: Date.now(), receipt: value });
        while (cache.size > 80) cache.delete(cache.keys().next().value!);
        setReceipt(value);
      })
      .catch(() => {
        if (active) setFailed(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [scope, attempt]);
  const scenes = receipt
    ? scenarioLabelsForIssue(issue.issue_id, issue.scenario_ids, receipt.items)
    : [];
  const ready =
    receipt?.status === 'complete' &&
    scenes.length > 0 &&
    scenes.every(
      (scene) =>
        scene.labels !== null && receipt.namespace && scene.labels.includes(receipt.namespace),
    );
  const triggerLabels = ready
    ? [
        ...new Set(
          receipt!.items
            .filter(
              (scene) =>
                scene.issue_id === issue.issue_id && issue.scenario_ids.includes(scene.scenario_id),
            )
            .flatMap((scene) =>
              scene.autotriage_labels.filter(
                (value) =>
                  (value.endsWith('_AutoTrigger') || value.endsWith('_ManualTrigger')) &&
                  value.startsWith(receipt!.namespace + '_') &&
                  scene.scenario_labels?.includes(value),
              ),
            ),
        ),
      ]
    : [];
  const status = !issue.eligible
    ? 'excluded'
    : !issue.scenario_ids.length
      ? 'pending'
      : receipt?.status || 'missing';
  return (
    <section
      className="min-w-0 rounded border p-3"
      aria-label={t('evaluation.scenario_evaluation_labels')}
    >
      <p className="font-medium">{t('scenario')}</p>
      <ul className="mt-1 space-y-1 break-all font-mono text-xs">
        {issue.scenario_ids.map((id) => (
          <li key={id}>{id}</li>
        ))}
      </ul>
      {!issue.scenario_ids.length && (
        <p className="mt-1 text-muted-foreground">{t('evaluation.issue_unmapped')}</p>
      )}
      <p className="mb-1.5 mt-3 text-xs text-muted-foreground">
        {t('evaluation.scenario_evaluation_labels')}
      </p>
      <div className="flex min-w-0 flex-wrap gap-1.5">
        <Badge variant="secondary" className="max-w-full whitespace-normal break-all">
          {label(issue.auto_label)}
        </Badge>
        <Badge variant="outline">
          {t(issue.ra_type === 2 ? 'autoTriage.autoTrigger' : 'autoTriage.manualTrigger')}
        </Badge>
      </div>
      {loading ? (
        <p role="status" className="mt-2 text-xs text-muted-foreground">
          {t('loading')}
        </p>
      ) : failed ? (
        <p role="alert" className="mt-2 text-xs text-destructive">
          {t('evaluation.scenario_labels_failed')}
        </p>
      ) : (
        <>
          <p role="status" className="mt-2 text-xs text-muted-foreground">
            {t(
              ready ? 'evaluation.scenario_labels_synced' : `evaluation.scenario_labels_${status}`,
              { defaultValue: t('evaluation.scenario_labels_unknown') },
            )}
          </p>
          {triggerLabels.map((value) => (
            <a
              key={value}
              className="mt-2 flex min-h-11 max-w-full items-start gap-1 rounded bg-primary/5 p-2 text-xs text-primary hover:underline"
              href={`https://voyager.intra.xiaojukeji.com/static/management/#/scenario/list?${new URLSearchParams({ scenario_tag_or: 'false', order_type: 'asc', page: '1', size: '10', labels: value })}`}
              target="_blank"
              rel="noreferrer"
              aria-label={t('evaluation.scenario_open_platform', { label: value })}
            >
              <code className="min-w-0 select-text break-all">{value}</code>
              <ExternalLink size={13} className="mt-0.5 shrink-0" />
            </a>
          ))}
        </>
      )}
      {!!issue.scenario_ids.length && (
        <details className="mt-2 min-w-0 border-t pt-1">
          <summary className="min-h-11 cursor-pointer py-3 text-xs font-medium">
            {t('evaluation.scenario_platform_labels')}
          </summary>
          {scenes.map((scene) => (
            <div key={scene.scenarioId} className="min-w-0 space-y-2 pb-3 text-xs">
              {scenes.length > 1 && <p className="break-all font-mono">{scene.scenarioId}</p>}
              {scene.labels === null ? (
                <p className="text-muted-foreground">{t('evaluation.scenario_labels_unknown')}</p>
              ) : scene.labels.length ? (
                <div className="flex min-w-0 flex-wrap gap-1">
                  {scene.labels.map((value) => (
                    <span
                      key={value}
                      className="max-w-full whitespace-pre-wrap break-all rounded bg-muted px-2 py-1 font-mono"
                    >
                      {value === '' ? t('autoTriage.result_empty') : value}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground">{t('evaluation.scenario_labels_empty')}</p>
              )}
            </div>
          ))}
          {!scenes.length && (
            <p className="py-2 text-xs text-muted-foreground">
              {t('evaluation.scenario_labels_unknown')}
            </p>
          )}
          <Button
            variant="ghost"
            className="min-h-11 max-w-full text-xs"
            disabled={loading}
            onClick={() => setAttempt((value) => value + 1)}
          >
            <RefreshCw size={13} />
            {t(failed ? 'autoTriage.retry' : 'evaluation.scenario_labels_reload')}
          </Button>
        </details>
      )}
    </section>
  );
}
