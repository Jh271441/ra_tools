import { releaseName } from '../lib/releaseName';
import { useMemo } from 'react';
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table';
import { Filter, Search } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { IssueListItem, SelectedIssueResult, VersionItem } from '../types';
import { cn } from '../lib/utils';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Select } from './ui/select';
import { Pagination } from './ui/pagination';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';

interface IssuesTableProps {
  items: IssueListItem[];
  versions: VersionItem[];
  total: number;
  loading: boolean;
  showVersionFilter?: boolean;
  page?: number;
  onPageChange?: (page: number) => void;
  pageSize?: number;
  onPageSizeChange?: (size: number) => void;
  filters: {
    version: string;
    rootCause: string;
    triggerType: string;
    precisionLabel: string;
    query: string;
  };
  onFiltersChange: (next: IssuesTableProps['filters']) => void;
  selectedResult: SelectedIssueResult | null;
  onSelectResult: (result: SelectedIssueResult) => void;
}

const columnHelper = createColumnHelper<IssueListItem>();

function labelVariant(label: string): 'success' | 'warning' | 'destructive' | 'outline' {
  if (label === 'TP') return 'success';
  if (label === 'FP') return 'destructive';
  if (label === 'FN') return 'warning';
  return 'outline';
}

function triggerBadge(value: boolean, positiveLabel: string, negativeLabel: string) {
  return (
    <Badge variant={value ? 'success' : 'outline'}>
      {value ? positiveLabel : negativeLabel}
    </Badge>
  );
}

export function IssuesTable({
  items,
  versions,
  total,
  loading,
  showVersionFilter = true,
  page = 1,
  onPageChange,
  pageSize = 20,
  onPageSizeChange,
  filters,
  onFiltersChange,
  selectedResult,
  onSelectResult,
}: IssuesTableProps) {
  const { t } = useTranslation();
  const versionLabelByKey = useMemo(
    () => new Map(versions.map((version) => [version.version_key, releaseName(version.version_key)])),
    [versions],
  );
  const columns = useMemo(
    () => [
      columnHelper.accessor('issue_id', {
        header: t('issue'),
        cell: (info) => (
          <div className="min-w-0">
            <div className="font-mono text-xs">{info.getValue() || '-'}</div>
            {info.row.original.issue_topic ? (
              <div className="mt-1 max-w-[220px] truncate text-xs text-muted-foreground">
                {info.row.original.issue_topic}
              </div>
            ) : null}
          </div>
        ),
      }),
      columnHelper.accessor('scenario_id', {
        header: t('scenario'),
        cell: (info) => (
          <div className="min-w-0">
            <div className="font-mono text-xs">{info.getValue()}</div>
            <div className="mt-1 max-w-[320px] truncate text-xs text-muted-foreground">
              {info.row.original.scenario_name || '-'}
            </div>
          </div>
        ),
      }),
      columnHelper.accessor('version_key', {
        header: t('version'),
        cell: (info) => (
          <div>
            <div className="font-medium">{versionLabelByKey.get(info.getValue()) || info.getValue()}</div>
            <div className="font-mono text-[11px] text-muted-foreground">{info.getValue()}</div>
          </div>
        ),
      }),
      columnHelper.accessor('precision_label', {
        header: 'Label',
        cell: (info) => <Badge variant={labelVariant(info.getValue())}>{info.getValue()}</Badge>,
      }),
      columnHelper.display({
        id: 'trigger_status',
        header: t('triggerStatus'),
        cell: (info) => (
          <div className="flex flex-wrap gap-1">
            {triggerBadge(info.row.original.road_triggered, t('roadTriggered'), t('roadNotTriggered'))}
            {triggerBadge(info.row.original.sim_triggered, t('simTriggered'), t('simNotTriggered'))}
          </div>
        ),
      }),
      columnHelper.accessor('trigger_type', {
        header: t('triggerType'),
      }),
      columnHelper.accessor('root_cause', {
        header: t('rootCause'),
      }),
      columnHelper.accessor('model_score_max', {
        header: t('modelScore'),
        cell: (info) => (info.getValue() == null ? '-' : info.getValue()?.toFixed(3)),
      }),
    ],
    [t, versionLabelByKey],
  );
  const table = useReactTable({
    data: items,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <Card className="min-w-0 overflow-hidden">
      <CardHeader className="border-b border-border/70">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <CardTitle>{t('issues')} ({total})</CardTitle>
            <p className="mt-1 text-[13px] leading-5 text-muted-foreground">{t('issuesSubtitle')}</p>
          </div>
          <Button variant="outline" size="sm" onClick={() => onFiltersChange({ version: showVersionFilter ? '' : filters.version, rootCause: '', triggerType: '', precisionLabel: '', query: '' })}>
            <Filter className="h-4 w-4" />
            {t('reset')}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="min-w-0 p-0">
        <div className="grid gap-3 border-b border-border/70 bg-accent/25 p-4 dark:bg-white/[0.02] md:grid-cols-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <input
              className="min-h-11 w-full rounded-md border border-input bg-card/80 pl-9 pr-3 text-sm shadow-sm outline-none transition focus:border-ring focus:ring-1 focus:ring-ring dark:bg-background/40"
              placeholder={t('search')}
              aria-label={t('search')}
              value={filters.query}
              onChange={(event) => onFiltersChange({ ...filters, query: event.target.value })}
            />
          </div>
          {showVersionFilter && <Select label={t('evaluation.issue_version')} value={filters.version} options={[{value:'',label:t('all')},...versions.map(version=>({value:version.version_key,label:releaseName(version.version_key)}))]} onChange={version=>onFiltersChange({...filters,version})}/>}
          <Select label={t('rootCause')} value={filters.rootCause} options={[{value:'',label:t('rootCause')},...['FP_RULE_SUPPRESS','SIM_DIVERGENCE','MODEL_OR_COUNTER_INSUFFICIENT','REPRODUCED','FALSE_POSITIVE','TRUE_NEGATIVE'].map(value=>({value,label:value}))]} onChange={rootCause=>onFiltersChange({...filters,rootCause})}/>
          <Select label={t('triggerType')} value={filters.triggerType} options={[{value:'',label:t('triggerType')},...['MODEL','FN','FP_SUPPRESSED','NONE'].map(value=>({value,label:value}))]} onChange={triggerType=>onFiltersChange({...filters,triggerType})}/>
          <Select label="TP / FP / FN / TN" value={filters.precisionLabel} options={[{value:'',label:'TP / FP / FN / TN'},...['TP','FP','FN','TN'].map(value=>({value,label:value}))]} onChange={precisionLabel=>onFiltersChange({...filters,precisionLabel})}/>
        </div>
        <div className="w-full min-w-0 max-w-[calc(100vw-2rem)] overflow-x-auto md:max-w-full">
          <table className="w-full min-w-[1160px] text-left text-[13px]">
            <thead className="bg-muted/45 dark:bg-white/[0.025]">
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <th key={header.id} className="h-10 px-4 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr>
                  <td colSpan={columns.length} className="px-4 py-10 text-center text-sm text-muted-foreground">
                    {loading ? t('loading') : t('noIssues')}
                  </td>
                </tr>
              ) : null}
              {table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  className={cn(
                    'cursor-pointer border-t border-border/60 transition-colors hover:bg-accent/40 dark:hover:bg-accent/25',
                    row.original.scenario_id === selectedResult?.scenario_id &&
                      row.original.version_key === selectedResult?.version_key &&
                      'bg-primary/5 shadow-[inset_3px_0_0_hsl(var(--primary))] dark:bg-primary/10',
                  )}
                  onClick={() =>
                    onSelectResult({
                      issue_id: row.original.issue_id,
                      scenario_id: row.original.scenario_id,
                      version_key: row.original.version_key,
                    })
                  }
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-4 py-2.5 align-middle">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {onPageChange && onPageSizeChange && <div className="p-3"><Pagination total={total} page={page} pageSize={pageSize} loading={loading} onPageChange={onPageChange} onPageSizeChange={onPageSizeChange}/></div>}
      </CardContent>
    </Card>
  );
}
