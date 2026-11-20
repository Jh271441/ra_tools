import { useEffect, useRef, useState } from 'react';
import { RefreshCw, Settings2, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { EvaluationBoard, EvaluationContext, MetricProfile } from '../types/evaluation';
import { releaseName } from '../lib/releaseName';
import { changeEvaluationRelease, validEvaluationDates } from '../lib/evaluationContext';
import { Button } from './ui/button';
import { Select } from './ui/select';

export function EvaluationSettings({ ctx, data, profiles, hideRelease, working, error, onApply, onClose, onManage, onRefresh }: {
  ctx: EvaluationContext; data: EvaluationBoard; profiles: MetricProfile[]; hideRelease: boolean; working: boolean; error: string;
  onApply: (value: EvaluationContext) => void; onClose: () => void; onManage: () => void; onRefresh: () => void;
}) {
  const { t, i18n } = useTranslation();
  const [draft, setDraft] = useState(() => ({ ...ctx }));
  const dialog = useRef<HTMLDialogElement>(null), origin = useRef<HTMLElement | null>(null);
  useEffect(() => {
    origin.current = document.activeElement as HTMLElement;
    dialog.current?.showModal();
    return () => { origin.current?.focus({ preventScroll: true }); };
  }, []);
  const dirty = (Object.keys(draft) as (keyof EvaluationContext)[]).some(key => draft[key] !== ctx[key]);
  const valid = validEvaluationDates(draft);
  const time = (value?: string) => value ? new Date(value).toLocaleString(i18n.language.startsWith('zh') ? 'zh-CN' : 'en-GB', { timeZone: 'Asia/Shanghai', hour12: false }) : '—';
  return <dialog ref={dialog} onCancel={event => { event.preventDefault(); onClose(); }} aria-labelledby="evaluation-settings-title" className="m-auto max-h-[90dvh] w-[min(600px,calc(100%_-_24px))] max-w-full overflow-y-auto rounded-lg border bg-card p-0 text-foreground shadow-xl backdrop:bg-black/40">
    <div className="flex items-center justify-between gap-3 border-b p-4">
      <h2 id="evaluation-settings-title" className="text-lg font-semibold">{t('evaluation.settings')}</h2>
      <Button variant="ghost" size="icon" className="h-11 w-11 shrink-0" aria-label={t('evaluation.close_settings')} onClick={onClose}><X size={17}/></Button>
    </div>
    <div className="grid min-w-0 gap-4 p-4">
      {!hideRelease && <label className="grid min-w-0 gap-1.5 text-sm">{t('version')}<Select label={t('autoTriage.release')} value={draft.release} options={data.versions.map(value => ({ value: value.release, label: releaseName(value.release) }))} onChange={release => setDraft(value => changeEvaluationRelease(value, release))}/></label>}
      <div className="flex min-w-0 flex-wrap items-end gap-2">
        <label className="grid min-w-0 flex-1 gap-1.5 text-sm">{t('evaluation.rule_set')}<Select label={t('evaluation.rule_set')} value={draft.profile_id || data.profile.id} options={profiles.filter(profile => profile.status === 'published').map(profile => ({ value: profile.id, label: profile.id === 'auto_triage_sql_v2' ? t('evaluation.default_rules') : profile.name }))} onChange={profile_id => setDraft(value => ({ ...value, profile_id }))}/></label>
        <Button className="min-h-11" variant="outline" onClick={onManage}><Settings2 size={16}/>{t('evaluation.manage_rules')}</Button>
      </div>
      <details className="rounded-md border px-3">
        <summary className="min-h-11 cursor-pointer py-3 text-sm font-medium">{t('evaluation.history_query')}</summary>
        <div className="grid min-w-0 gap-3 pb-3 sm:grid-cols-2">
          {(['date_start', 'date_end'] as const).map(key => <label key={key} className="grid min-w-0 gap-1.5 text-sm">{t(key === 'date_start' ? 'evaluation.sample_date_start' : 'evaluation.sample_date_end')}<input type="date" className="min-h-11 w-full min-w-0 max-w-full rounded-md border bg-background px-3 text-sm" value={draft[key] || ''} onChange={event => setDraft(value => ({ ...value, [key]: event.target.value }))}/></label>)}
        </div>
      </details>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-sm">
        <span className="text-muted-foreground">{t('evaluation.saved_results')}</span>
        <Button className="min-h-11" variant="outline" title={t(dirty ? 'evaluation.apply_before_refresh' : 'evaluation.recalculate_plan')} disabled={dirty || data.sample_source.status !== 'ready' || working} onClick={onRefresh}><RefreshCw size={16} className={working ? 'animate-spin' : ''}/>{t(working ? 'evaluation.recalculating' : 'evaluation.recalculate_short')}</Button>
      </div>
      {error && <p role="alert" className="break-words text-sm text-destructive">{t(`evaluation.error_${error}`, { defaultValue: t('evaluation.action_failed') })}</p>}
      <details className="rounded-md border px-3 text-xs text-muted-foreground">
        <summary className="min-h-11 cursor-pointer py-3 text-sm">{t('evaluation.source_details')}</summary>
        <div className="space-y-2 break-words pb-3 leading-5">
          <p>{t('evaluation.sample_scope', { start: ctx.date_start || '—', end: ctx.date_end || '—' })} · {t('autoTriage.shanghai')}</p>
          <p>{t('evaluation.checked_at')} {time(data.revision?.label_checked_at)}</p>
          {data.sample_source.status === 'ready' && <p>{t('evaluation.sample_saved', { amount: data.sample_source.row_count?.toLocaleString(i18n.language), time: time(data.sample_source.stored_at) })}</p>}
          <p>{t('evaluation.profile_version')} <code className="break-all">{data.profile.id}</code></p>
          <p>{t(data.cron.processing_enabled === false ? 'evaluation.auto_tracking_paused' : 'evaluation.auto_tracking')} · {t('evaluation.auto_tracking_note', { seconds: data.cron.poll_seconds || 30 })}</p>
          <p>{t('evaluation.offline_source_note')}</p><p>{t('evaluation.independent_counts')}</p><p>{t('evaluation.manual_policy')}</p>
        </div>
      </details>
    </div>
    <div className="flex flex-wrap justify-end gap-2 border-t p-4">
      <Button className="min-h-11" variant="outline" onClick={onClose}>{t('evaluation.cancel_settings')}</Button>
      <Button className="min-h-12" disabled={!valid || working} onClick={() => { if (dirty) onApply(draft); onClose(); }}>{t('evaluation.apply_settings')}</Button>
    </div>
  </dialog>;
}
