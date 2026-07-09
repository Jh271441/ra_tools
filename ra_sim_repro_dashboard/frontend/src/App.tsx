import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  BarChart3,
  Database,
  Filter,
  GitCompareArrows,
  HeartPulse,
  LayoutDashboard,
  ListChecks,
  PanelLeftClose,
  RotateCcw,
  Search,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from './api/client';
import { IssueDetail } from './components/IssueDetail';
import { IssuesTable } from './components/IssuesTable';
import { Overview } from './components/Overview';
import { SystemStatus } from './components/SystemStatus';
import { TopControls } from './components/TopControls';
import { Badge } from './components/ui/badge';
import { Button } from './components/ui/button';
import { cn } from './lib/utils';
import type { IssueListItem, KpiSummary, RefreshJob, SelectedIssueResult, SummaryResponse, VersionItem } from './types';

type Page = 'overview' | 'issues' | 'status';

// Lightweight history routing: module switches map to /sim/overview,
// /sim/issues, /sim/status so browser/mouse back-forward navigates between
// modules instead of leaving the app. BASE_URL is '/sim/' in this build.
const BASE_PATH = import.meta.env.BASE_URL.replace(/\/$/, '');
const PAGES: Page[] = ['overview', 'issues', 'status'];

function pageFromLocation(): Page {
  const path = window.location.pathname;
  for (const candidate of PAGES) {
    if (path === `${BASE_PATH}/${candidate}` || path.startsWith(`${BASE_PATH}/${candidate}/`)) {
      return candidate;
    }
  }
  return 'overview';
}

const defaultFilters = {
  version: '',
  rootCause: '',
  triggerType: '',
  precisionLabel: '',
  query: '',
};

const defaultSourceFilters = {
  platformGen: '',
  versionCategory: '',
  bigVersion: '',
  testVersion: '',
};

function stringValue(value: unknown) {
  return value == null ? '' : String(value);
}

function pct(value: number | undefined) {
  return `${Math.round((value ?? 0) * 1000) / 10}%`;
}

function addOption(target: Set<string>, value: unknown) {
  const text = stringValue(value).trim();
  if (text) target.add(text);
}

function matchesMeta(value: unknown, expected: string) {
  if (!expected) return true;
  return stringValue(value) === expected;
}

function SelectFilter({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <label className="grid gap-1.5 text-xs font-medium text-muted-foreground">
      <span className="inline-flex items-center gap-1">
        <Filter className="h-3.5 w-3.5" />
        {label}
      </span>
      <select
        className="h-9 rounded-md border border-input bg-card/80 px-3 text-sm font-normal text-foreground shadow-sm outline-none transition focus:border-ring focus:ring-1 focus:ring-ring dark:bg-background/40"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{t('all')}</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function App() {
  const { t } = useTranslation();
  const [page, setPageState] = useState<Page>(pageFromLocation);

  const setPage = useCallback((next: Page) => {
    setPageState(next);
    const target = `${BASE_PATH}/${next}`;
    if (window.location.pathname !== target) {
      window.history.pushState({ page: next }, '', target);
    }
  }, []);

  useEffect(() => {
    // Normalize bare /sim/ to a canonical module URL without adding a history entry.
    window.history.replaceState({ page: pageFromLocation() }, '', `${BASE_PATH}/${pageFromLocation()}`);
    const onPopState = () => setPageState(pageFromLocation());
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);
  const [dark, setDark] = useState(() => localStorage.getItem('theme') === 'dark');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem('sidebarCollapsed') === '1');
  const [versions, setVersions] = useState<VersionItem[]>([]);
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [comparison, setComparison] = useState<KpiSummary[]>([]);
  const [issues, setIssues] = useState<IssueListItem[]>([]);
  const [issuesLoading, setIssuesLoading] = useState(false);
  const [issueTotal, setIssueTotal] = useState(0);
  const [filters, setFilters] = useState(defaultFilters);
  const [sourceFilters, setSourceFilters] = useState(defaultSourceFilters);
  const [selectedResult, setSelectedResult] = useState<SelectedIssueResult | null>(null);
  const [refreshJob, setRefreshJob] = useState<RefreshJob | null>(null);
  const [error, setError] = useState<string>('');

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
    localStorage.setItem('theme', dark ? 'dark' : 'light');
  }, [dark]);

  useEffect(() => {
    localStorage.setItem('sidebarCollapsed', sidebarCollapsed ? '1' : '0');
  }, [sidebarCollapsed]);

  const refreshing = refreshJob?.status === 'queued' || refreshJob?.status === 'running';

  const loadDashboard = useCallback(async () => {
    setError('');
    const versionsResult = await api.versions();
    setVersions(versionsResult.versions);
    try {
      const [summaryResult, comparisonResult] = await Promise.all([api.summary(), api.comparison()]);
      setSummary(summaryResult);
      setComparison(comparisonResult);
    } catch (err) {
      setSummary(null);
      setComparison([]);
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  const loadIssues = useCallback(async () => {
    setIssuesLoading(true);
    try {
      const params = new URLSearchParams({ page: '1', page_size: '100' });
      if (filters.version) params.set('version', filters.version);
      if (filters.rootCause) params.set('root_cause', filters.rootCause);
      if (filters.triggerType) params.set('trigger_type', filters.triggerType);
      if (filters.precisionLabel) params.set('precision_label', filters.precisionLabel);
      const query = filters.query.trim();
      if (query) {
        if (query.toLowerCase().startsWith('cn')) params.set('issue_id', query);
        else params.set('scenario_id', query);
      }
      const result = await api.issues(params);
      setIssues(result.items);
      setIssueTotal(result.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIssuesLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    void loadDashboard();
  }, [loadDashboard]);

  useEffect(() => {
    void loadIssues();
  }, [loadIssues]);

  useEffect(() => {
    if (!issues.length) {
      setSelectedResult(null);
      return;
    }
    const currentStillVisible = selectedResult
      ? issues.some(
          (item) =>
            item.scenario_id === selectedResult.scenario_id &&
            item.version_key === selectedResult.version_key,
        )
      : false;
    if (!currentStillVisible) {
      const first = issues[0];
      setSelectedResult({
        issue_id: first.issue_id,
        scenario_id: first.scenario_id,
        version_key: first.version_key,
      });
    }
  }, [issues, selectedResult]);

  useEffect(() => {
    if (!refreshJob || refreshJob.status === 'completed' || refreshJob.status === 'failed') return;
    const timer = window.setInterval(() => {
      void api.refreshStatus(refreshJob.job_id).then((job) => {
        setRefreshJob(job);
        if (job.status === 'completed') {
          void loadDashboard();
          void loadIssues();
        }
      });
    }, 1200);
    return () => window.clearInterval(timer);
  }, [refreshJob, loadDashboard, loadIssues]);

  const current = useMemo(() => versions.find((item) => item.is_current), [versions]);
  const versionCards = comparison.length ? comparison : summary ? [summary.current] : [];
  const metadataByVersion = useMemo(
    () => new Map(versions.map((version) => [version.version_key, version.metadata_json || {}])),
    [versions],
  );
  const sourceOptions = useMemo(() => {
    const values = {
      platformGen: new Set<string>(),
      versionCategory: new Set<string>(),
      bigVersion: new Set<string>(),
      testVersion: new Set<string>(),
    };
    for (const version of versions) {
      const meta = version.metadata_json || {};
      addOption(values.platformGen, meta.platform_gen);
      addOption(values.versionCategory, meta.version_category);
      addOption(values.bigVersion, meta.big_version);
      addOption(values.testVersion, meta.test_version);
    }
    return {
      platformGen: [...values.platformGen],
      versionCategory: [...values.versionCategory],
      bigVersion: [...values.bigVersion],
      testVersion: [...values.testVersion],
    };
  }, [versions]);
  const sourceFilterActive = Object.values(sourceFilters).some(Boolean);
  const matchedVersionKeys = useMemo(() => {
    const matched = versions
      .filter((version) => {
        const meta = version.metadata_json || {};
        return (
          matchesMeta(meta.platform_gen, sourceFilters.platformGen) &&
          matchesMeta(meta.version_category, sourceFilters.versionCategory) &&
          matchesMeta(meta.big_version, sourceFilters.bigVersion) &&
          matchesMeta(meta.test_version, sourceFilters.testVersion)
        );
      })
      .map((version) => version.version_key);
    return new Set(matched);
  }, [sourceFilters, versions]);
  const visibleVersionCards = sourceFilterActive
    ? versionCards.filter((item) => matchedVersionKeys.has(item.version_key))
    : versionCards;

  async function handleRefresh() {
    setError('');
    const job = await api.refresh();
    setRefreshJob(job);
  }

  function openIssues(nextFilters: Partial<typeof defaultFilters>) {
    setFilters({ ...defaultFilters, ...nextFilters });
    setPage('issues');
  }

  function applySourceFilters() {
    const keys = [...matchedVersionKeys];
    setFilters((value) => ({
      ...value,
      version: keys.length === 1 ? keys[0] : '',
    }));
  }

  function resetSourceFilters() {
    setSourceFilters(defaultSourceFilters);
    setFilters((value) => ({ ...value, version: '' }));
  }

  return (
    <div className="min-h-screen text-foreground">
      <div className="min-h-screen lg:flex">
        <aside
          className={cn(
            'fixed inset-y-0 left-0 z-30 hidden overflow-hidden border-r border-border/70 bg-card/86 backdrop-blur-xl transition-[width] duration-180 ease-out dark:bg-background/88 lg:flex lg:flex-col',
            sidebarCollapsed ? 'w-[72px]' : 'w-72',
          )}
        >
          <div
            className={cn(
              'flex h-16 items-center border-b border-border/70',
              sidebarCollapsed ? 'justify-center px-3' : 'gap-3 px-5',
            )}
          >
            <button
              type="button"
              className="group flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground shadow-sm shadow-primary/20 transition-[box-shadow,opacity,transform] duration-150 hover:opacity-95 hover:shadow-md hover:shadow-primary/25 active:scale-95 focus:outline-none focus:ring-2 focus:ring-ring"
              onClick={() => setSidebarCollapsed((value) => !value)}
              title={sidebarCollapsed ? t('expandSidebar') : t('collapseSidebar')}
              aria-label={sidebarCollapsed ? t('expandSidebar') : t('collapseSidebar')}
            >
              <Activity className="h-4 w-4" />
            </button>
            {!sidebarCollapsed ? (
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] font-semibold">{t('brandTitle')}</div>
                <div className="text-[11px] text-muted-foreground">{t('brandSubtitle')}</div>
              </div>
            ) : null}
            {!sidebarCollapsed ? (
              <Button
                variant="ghost"
                size="icon"
                className="ml-auto h-8 w-8"
                onClick={() => setSidebarCollapsed(true)}
                title={t('collapseSidebar')}
                aria-label={t('collapseSidebar')}
              >
                <PanelLeftClose className="h-4 w-4" />
              </Button>
            ) : null}
          </div>

          <nav className="grid gap-1 p-3">
            <Button
              variant={page === 'overview' ? 'secondary' : 'ghost'}
              className={cn(sidebarCollapsed ? 'sidebar-icon-button' : 'justify-start')}
              onClick={() => setPage('overview')}
              title={t('overview')}
              aria-label={t('overview')}
            >
              <LayoutDashboard className="h-4 w-4" />
              {!sidebarCollapsed ? t('overview') : null}
            </Button>
            <Button
              variant={page === 'issues' ? 'secondary' : 'ghost'}
              className={cn(sidebarCollapsed ? 'sidebar-icon-button' : 'justify-start')}
              onClick={() => setPage('issues')}
              title={t('issues')}
              aria-label={t('issues')}
            >
              <ListChecks className="h-4 w-4" />
              {!sidebarCollapsed ? t('issues') : null}
            </Button>
            <Button
              variant={page === 'status' ? 'secondary' : 'ghost'}
              className={cn(sidebarCollapsed ? 'sidebar-icon-button' : 'justify-start')}
              onClick={() => setPage('status')}
              title={t('systemStatus')}
              aria-label={t('systemStatus')}
            >
              <HeartPulse className="h-4 w-4" />
              {!sidebarCollapsed ? t('systemStatus') : null}
            </Button>
          </nav>

          <div className={cn('mt-auto grid gap-3 border-t border-border/70', sidebarCollapsed ? 'p-3' : 'p-4')}>
            <TopControls
              dark={dark}
              onToggleDark={() => setDark((value) => !value)}
              onRefresh={handleRefresh}
              refreshing={refreshing}
              compact={sidebarCollapsed}
            />
            {!sidebarCollapsed && refreshJob ? (
              <Badge variant={refreshing ? 'warning' : refreshJob.status === 'completed' ? 'success' : 'destructive'} className="justify-center">
                {refreshJob.status} {refreshJob.progress}%
              </Badge>
            ) : null}
            <div
              className={cn(
                sidebarCollapsed
                  ? 'sidebar-icon-button flex cursor-pointer items-center justify-center'
                  : 'metric-surface rounded-lg border p-3',
              )}
              role={sidebarCollapsed ? 'button' : undefined}
              tabIndex={sidebarCollapsed ? 0 : undefined}
              title={current?.label || current?.version_key || t('currentVersion')}
              onClick={sidebarCollapsed ? () => openIssues({ version: current?.version_key || '' }) : undefined}
              onKeyDown={
                sidebarCollapsed
                  ? (event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        openIssues({ version: current?.version_key || '' });
                      }
                    }
                  : undefined
              }
            >
              {sidebarCollapsed ? (
                <GitCompareArrows className="h-4 w-4 text-primary" />
              ) : (
                <>
                  <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
                    <GitCompareArrows className="h-3.5 w-3.5" />
                    {t('currentVersion')}
                  </div>
                  <div className="truncate text-[13px] font-semibold">{current?.label || current?.version_key || '-'}</div>
                  <div className="mt-1 font-mono text-[11px] text-muted-foreground">
                    {current?.sim_job_id ? `job ${current.sim_job_id}` : 'job -'}
                  </div>
                </>
              )}
            </div>
          </div>
        </aside>

        <div
          className={cn(
            'flex min-h-screen min-w-0 flex-1 flex-col transition-[padding-left] duration-180 ease-out',
            sidebarCollapsed ? 'lg:pl-[72px]' : 'lg:pl-72',
          )}
        >
          <header className="sticky top-0 z-20 border-b border-border/70 bg-background/80 backdrop-blur-xl supports-[backdrop-filter]:bg-background/60 lg:hidden">
            <div className="flex flex-col gap-3 px-4 py-3">
              <div className="min-w-0">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <Badge variant="secondary">
                    <Database className="h-3.5 w-3.5" />
                    {current?.label || '-'}
                  </Badge>
                  {refreshJob ? (
                    <Badge variant={refreshing ? 'warning' : refreshJob.status === 'completed' ? 'success' : 'destructive'}>
                      {refreshJob.status} {refreshJob.progress}%
                    </Badge>
                  ) : null}
                </div>
                <h1 className="truncate text-lg font-semibold tracking-normal">
                  {page === 'overview' ? t('appTitle') : page === 'issues' ? t('issues') : t('systemStatus')}
                </h1>
              </div>
              <div className="grid gap-2">
                <nav className="grid grid-cols-3 gap-1 rounded-lg bg-muted p-1">
                  <Button
                    variant={page === 'overview' ? 'default' : 'ghost'}
                    size="sm"
                    onClick={() => setPage('overview')}
                  >
                    <BarChart3 className="h-4 w-4" />
                    {t('overview')}
                  </Button>
                  <Button
                    variant={page === 'issues' ? 'default' : 'ghost'}
                    size="sm"
                    onClick={() => setPage('issues')}
                  >
                    <ListChecks className="h-4 w-4" />
                    {t('issues')}
                  </Button>
                  <Button
                    variant={page === 'status' ? 'default' : 'ghost'}
                    size="sm"
                    onClick={() => setPage('status')}
                  >
                    <HeartPulse className="h-4 w-4" />
                    {t('systemStatus')}
                  </Button>
                </nav>
                <TopControls
                  dark={dark}
                  onToggleDark={() => setDark((value) => !value)}
                  onRefresh={handleRefresh}
                  refreshing={refreshing}
                  className="grid grid-cols-3"
                />
              </div>
            </div>
          </header>

          <main className="grid min-w-0 gap-5 p-4 md:p-6">
            {page !== 'status' ? (
            <section className="apple-panel fine-grid grid gap-4 rounded-lg border p-4">
              <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <Badge variant="secondary">
                    <Database className="h-3.5 w-3.5" />
                    {t('currentVersion')}: {current?.label || current?.version_key || '-'}
                  </Badge>
                  {current?.sim_job_id ? <Badge variant="outline">{t('job')} {current.sim_job_id}</Badge> : null}
                  <Badge variant="outline">{versions.length} {t('versions')}</Badge>
                </div>
                <div className="text-xs text-muted-foreground">
                  {summary ? `${t('generated')} ${new Date(summary.generated_at).toLocaleString()}` : t('noSnapshot')}
                </div>
              </div>

              <div className="grid gap-3 border-t border-border/60 pt-3 md:grid-cols-2 xl:grid-cols-[repeat(4,minmax(0,1fr))_auto_auto]">
                <SelectFilter
                  label={t('platformGen')}
                  value={sourceFilters.platformGen}
                  options={sourceOptions.platformGen}
                  onChange={(value) => setSourceFilters((current) => ({ ...current, platformGen: value }))}
                />
                <SelectFilter
                  label={t('versionCategory')}
                  value={sourceFilters.versionCategory}
                  options={sourceOptions.versionCategory}
                  onChange={(value) => setSourceFilters((current) => ({ ...current, versionCategory: value }))}
                />
                <SelectFilter
                  label={t('bigVersion')}
                  value={sourceFilters.bigVersion}
                  options={sourceOptions.bigVersion}
                  onChange={(value) => setSourceFilters((current) => ({ ...current, bigVersion: value }))}
                />
                <SelectFilter
                  label={t('testVersion')}
                  value={sourceFilters.testVersion}
                  options={sourceOptions.testVersion}
                  onChange={(value) => setSourceFilters((current) => ({ ...current, testVersion: value }))}
                />
                <Button variant="outline" size="sm" className="h-9 md:self-end" onClick={resetSourceFilters}>
                  <RotateCcw className="h-4 w-4" />
                  {t('reset')}
                </Button>
                <Button size="sm" className="h-9 md:self-end" onClick={applySourceFilters}>
                  <Search className="h-4 w-4" />
                  {t('searchAction')}
                </Button>
              </div>

              {page === 'issues' && versionCards.length ? (
                <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-5">
                  {visibleVersionCards.slice(0, 5).map((item) => {
                    const active = item.version_key === current?.version_key;
                    const meta = metadataByVersion.get(item.version_key) || {};
                    return (
                      <div
                        key={item.version_key}
                        role="button"
                        tabIndex={0}
                        className={cn(
                          'metric-surface min-w-0 cursor-pointer rounded-lg border p-3 transition hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md hover:shadow-primary/10 focus:outline-none focus:ring-2 focus:ring-ring',
                          active && 'border-primary/40 bg-primary/5 dark:bg-primary/10',
                        )}
                        onClick={() => openIssues({ version: item.version_key })}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault();
                            openIssues({ version: item.version_key });
                          }
                        }}
                      >
                        <div className="mb-3 flex items-center justify-between gap-2">
                          <div className="min-w-0 truncate text-sm font-semibold">{item.label || item.version_key}</div>
                          <span
                            className={cn(
                              'h-2 w-2 shrink-0 rounded-full bg-muted-foreground/40',
                              active && 'bg-primary shadow-[0_0_0_4px_hsl(var(--primary)/0.12)]',
                            )}
                          />
                        </div>
                        <div className="mb-3 truncate font-mono text-[11px] text-muted-foreground">
                          {stringValue(meta.sim_plan) || stringValue(meta.binary) || item.version_key}
                        </div>
                        <div className="grid grid-cols-3 gap-2 text-xs">
                          <div>
                            <div className="text-muted-foreground">{t('shortRepro')}</div>
                            <div className="mt-1 font-mono text-sm font-semibold">{pct(item.sim_repro_rate)}</div>
                          </div>
                          <div>
                            <div className="text-muted-foreground">{t('shortPrecision')}</div>
                            <div className="mt-1 font-mono text-sm font-semibold">{pct(item.precision)}</div>
                          </div>
                          <div>
                            <div className="text-muted-foreground">{t('shortRecall')}</div>
                            <div className="mt-1 font-mono text-sm font-semibold">{pct(item.recall)}</div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : null}
            </section>
            ) : null}

            {error && page !== 'status' ? (
              <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">
                {error}
              </div>
            ) : null}

            {page === 'status' ? (
              <SystemStatus />
            ) : page === 'overview' ? (
              <Overview summary={summary} comparison={comparison} onOpenIssues={openIssues} />
            ) : (
              <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(380px,0.75fr)]">
                <IssuesTable
                  items={issues}
                  versions={versions}
                  total={issueTotal}
                  loading={issuesLoading}
                  filters={filters}
                  onFiltersChange={setFilters}
                  selectedResult={selectedResult}
                  onSelectResult={setSelectedResult}
                />
                <IssueDetail selected={selectedResult} />
              </div>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
