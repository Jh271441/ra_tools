import { useTranslation } from 'react-i18next';
import type { ReproductionResult, ReproductionSummary } from '../types/reproduction';

export function ReproductionStatus({ value }: { value: ReproductionResult }) {
  const { t } = useTranslation();
  return <span title={t('reproduction.policy')} className={value.matched == null ? 'text-amber-700 dark:text-amber-400' : undefined}>{t(`reproduction.${value.status}`, { defaultValue: t('reproduction.pending') })}</span>;
}

export function ReproductionDetails({ value }: { value: ReproductionSummary }) {
  const { t, i18n } = useTranslation();
  const n = (count: number) => count.toLocaleString(i18n.language);
  return <details className="border-t text-xs text-muted-foreground" data-reproduction-scope>
    <summary className="flex min-h-11 cursor-pointer flex-wrap items-center justify-between gap-2 py-3">
      <span>{t('reproduction.verified', { matched: n(value.matched), evaluated: n(value.evaluated) })}</span>
      {!!value.pending && <span className="text-amber-700 dark:text-amber-400">{t('reproduction.pending_count', { amount: n(value.pending) })}</span>}
    </summary>
    <p className="pb-2 leading-5">{t('reproduction.policy')}</p>
    <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-2 pb-3">{Object.entries(value.statuses).filter(([,count]) => count > 0).map(([status,count]) => <div className="contents" key={status}><dt className="break-words">{t(`reproduction.${status}`, { defaultValue: t('reproduction.pending') })}</dt><dd className="font-mono tabular-nums">{n(count)}</dd></div>)}</dl>
  </details>;
}
