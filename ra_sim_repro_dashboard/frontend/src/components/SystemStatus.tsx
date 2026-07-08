import { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  CircleSlash,
  Database,
  FileCog,
  FolderOpen,
  History,
  ListTree,
  RefreshCw,
  Server,
  XCircle,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';
import { cn } from '../lib/utils';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import type { SystemCheck, SystemCheckStatus, SystemStatusResponse } from '../types';

const AUTO_REFRESH_MS = 30_000;

const checkIcons: Record<string, typeof Database> = {
  database: Database,
  redis: Server,
  queue: ListTree,
  versions_config: FileCog,
  mock_data: FolderOpen,
  last_refresh: History,
};

const statusBadgeVariant: Record<SystemCheckStatus, 'success' | 'warning' | 'destructive' | 'secondary'> = {
  ok: 'success',
  warn: 'warning',
  error: 'destructive',
  skipped: 'secondary',
};

function StatusIcon({ status, className }: { status: SystemCheckStatus; className?: string }) {
  if (status === 'ok') return <CheckCircle2 className={cn('text-emerald-500', className)} />;
  if (status === 'warn') return <AlertTriangle className={cn('text-amber-500', className)} />;
  if (status === 'error') return <XCircle className={cn('text-red-500', className)} />;
  return <CircleSlash className={cn('text-muted-foreground', className)} />;
}

function formatUptime(seconds: number) {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m ${seconds % 60}s`;
}

function extraValue(value: unknown) {
  if (value == null || value === '') return '-';
  return String(value);
}

function CheckCard({ check }: { check: SystemCheck }) {
  const { t } = useTranslation();
  const Icon = checkIcons[check.key] || Server;
  const extras = Object.entries(check.extra || {});
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-2 space-y-0">
        <CardTitle className="flex min-w-0 items-center gap-2">
          <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="truncate">{t(`statusCheck.${check.key}`, check.key)}</span>
        </CardTitle>
        <Badge variant={statusBadgeVariant[check.status]} className="shrink-0">
          <StatusIcon status={check.status} className="h-3.5 w-3.5" />
          {t(`statusValue.${check.status}`, check.status)}
        </Badge>
      </CardHeader>
      <CardContent className="grid gap-3">
        <div className="truncate font-mono text-[11px] text-muted-foreground" title={check.detail}>
          {check.detail || '-'}
        </div>
        {check.error ? (
          <div className="rounded-md border border-destructive/30 bg-destructive/10 p-2 text-xs text-destructive">
            {check.error}
          </div>
        ) : null}
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div>
            <div className="text-muted-foreground">{t('latency')}</div>
            <div className="mt-1 font-mono text-sm font-semibold">
              {check.latency_ms != null ? `${check.latency_ms} ms` : '-'}
            </div>
          </div>
          {extras.map(([key, value]) => (
            <div key={key} className="min-w-0">
              <div className="truncate text-muted-foreground" title={key}>
                {key}
              </div>
              <div className="mt-1 truncate font-mono text-sm font-semibold" title={extraValue(value)}>
                {extraValue(value)}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export function SystemStatus() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<SystemStatusResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.systemStatus();
      setStatus(result);
      setCheckedAt(new Date());
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), AUTO_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  const overall: SystemCheckStatus = error ? 'error' : status?.overall ?? 'skipped';

  return (
    <div className="grid min-w-0 gap-5">
      <Card>
        <CardContent className="flex flex-col gap-4 p-5 md:flex-row md:items-center md:justify-between">
          <div className="flex min-w-0 items-center gap-3">
            <StatusIcon status={overall} className="h-8 w-8 shrink-0" />
            <div className="min-w-0">
              <div className="text-base font-semibold">
                {t(`statusOverall.${overall}`, overall)}
              </div>
              <div className="text-xs text-muted-foreground">
                {checkedAt
                  ? `${t('lastChecked')} ${checkedAt.toLocaleTimeString()} · ${t('autoRefreshEvery')} ${AUTO_REFRESH_MS / 1000}s`
                  : t('loading')}
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {status ? (
              <>
                <Badge variant="outline">
                  {t('backendUptime')}: {formatUptime(status.uptime_seconds)}
                </Badge>
                <Badge variant={status.enable_rq ? 'success' : 'secondary'}>
                  RQ {status.enable_rq ? 'ON' : 'OFF'}
                </Badge>
              </>
            ) : null}
            <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
              <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
              {t('checkNow')}
            </Button>
          </div>
        </CardContent>
      </Card>

      {error ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
          {t('statusFetchFailed')}: {error}
        </div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {(status?.checks || []).map((check) => (
          <CheckCard key={check.key} check={check} />
        ))}
      </div>
    </div>
  );
}
