import { useTranslation } from 'react-i18next';
import { releaseName } from '../lib/releaseName';
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { ExternalLink } from 'lucide-react';
import type { VersionItem } from '../types';
import { cn } from '../lib/utils';
import { localTime, request, stateNames, type SourceIssue, type Workflow } from './ReleaseWorkflow';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';

interface Props {
  versions: VersionItem[];
  version: string;
  onVersionChange: (version: string) => void;
  onHistoryChange: (shown: boolean) => void;
  history: ReactNode;
}

interface CollectionVersion {
  release: string; collection_status: 'stable' | 'collecting' | 'pending'; source: 'snapshot' | 'observation';
  issue_count: number | null; auto_count: number | null; manual_count: number | null;
  synced_at: string | null; last_issue_at: string | null; quiet_since: string | null; eligible_at: string | null;
  stale: boolean; monitor_status: string | null;
}
interface CollectionInventory { default_release: string | null; versions: CollectionVersion[] }
const collectionNames = { stable: '已收集', collecting: '收集中', pending: '待同步' };

export function ReleaseIssues({ versions, version, onVersionChange, onHistoryChange, history }: Props) {
  const { t } = useTranslation();
  const [data, setData] = useState<Workflow | null>(null);
  const [inventory, setInventory] = useState<CollectionInventory | null>(null);
  const [rows, setRows] = useState<SourceIssue[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState('');
  const [label, setLabel] = useState('');
  const [selectedKey, setSelectedKey] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [notice, setNotice] = useState('');
  const generation = useRef(0);
  const selectedRelease = version === '@stable' ? inventory?.default_release : version === '@current' ? data?.current_version : version;
  const collection = inventory?.versions.find(item => item.release === selectedRelease);
  const observing = collection?.source === 'observation';
  const usesSource = version === '@stable' || Boolean(collection) || version === '@current' || version === data?.current_version || Boolean(data?.periods.some(
    period => period.release === version && period.status === 'completed' && (period.verified || period.basis === 'inferred'),
  ));

  useEffect(() => {
    let active = true;
    const load = () => void Promise.all([request<Workflow>(), request<CollectionInventory>('/versions')]).then(([value, catalog]) => {
      if (active) { setData(value); setInventory(catalog); setError(''); }
    }).catch(err => { if (active) setError(err instanceof Error ? err.message : String(err)); });
    load();
    const timer = window.setInterval(load, 30000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (data) onHistoryChange(!usesSource);
  }, [data, usesSource, onHistoryChange]);

  useEffect(() => {
    setPage(1); setQuery(''); setLabel(''); setSelectedKey(''); setRows([]); setTotal(0);
  }, [version]);

  const loadRows = useCallback(async () => {
    const id = ++generation.current;
    if (!usesSource) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({ release: version, page: String(page), page_size: '25', query, label });
      const issues = await request<{ items: SourceIssue[]; total: number }>(`/issues?${params}`);
      if (id === generation.current) { setRows(issues.items); setTotal(issues.total); setError(''); }
    } catch (err) {
      if (id === generation.current) setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (id === generation.current) setLoading(false);
    }
  }, [usesSource, version, page, query, label]);
  useEffect(() => {
    void loadRows();
    const timer = window.setInterval(() => void loadRows(), 30000);
    return () => { generation.current++; window.clearInterval(timer); };
  }, [loadRows]);

  const rowKey = (row: SourceIssue) => `${row.issue_id}-${row.scenario_id}`;
  const selected = rows.find(row => rowKey(row) === selectedKey) || rows[0];
  const options = new Map(versions.map(item => [item.version_key, releaseName(item.version_key)]));
  data?.periods.filter(period => period.status === 'completed' && (period.verified || period.basis === 'inferred'))
    .forEach(period => { if (!options.has(period.release)) options.set(period.release, releaseName(period.release)); });

  inventory?.versions.forEach(item => options.set(item.release, releaseName(item.release)));

  async function sync() {
    setSyncing(true); setNotice('');
    try {
      await request('/sync', 'POST');
      setNotice('已请求同步，后台完成后自动更新。');
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setSyncing(false); }
  }

  return <div className="min-w-0 space-y-4">
    <Card>
      <CardHeader><CardTitle>单版本 Issue 明细</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-wrap items-center gap-3 text-sm">
        <label className="flex min-w-0 max-w-full items-center gap-2">版本
          <select aria-label="Issue 版本" className="min-w-0 max-w-full rounded border bg-background p-2" value={version} onChange={event => onVersionChange(event.target.value)}>
            <option value="@stable">最新已收集{inventory?.default_release ? ` · ${releaseName(inventory.default_release)}` : ' · 暂无'}</option>
            {version === '@current' && <option value="@current">当前业务版本 · {releaseName(data?.current_version)}</option>}
            {(['stable', 'collecting', 'pending', 'archived'] as const).map(group => {
              const items = [...options].filter(([key]) => (inventory?.versions.find(item => item.release === key)?.collection_status || 'archived') === group);
              return items.length ? <optgroup key={group} label={group === 'archived' ? '历史归档' : collectionNames[group]}>{items.sort(([a], [b]) => b.localeCompare(a)).map(([key, text]) => <option key={key} value={key} title={key}>{text}</option>)}</optgroup> : null;
            })}
          </select>
        </label>
        {collection && <span className={cn('rounded-full px-2.5 py-1 text-xs', collection.collection_status === 'stable' ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400' : 'bg-blue-500/10 text-blue-700 dark:text-blue-400')}>{collectionNames[collection.collection_status]}</span>}
        {usesSource && <Button variant="outline" className="sm:ml-auto" disabled={syncing} onClick={() => void sync()}>同步 Issue</Button>}
        {collection ? <div className="w-full space-y-2 text-xs text-muted-foreground">
          <p>{collection.issue_count == null ? '数量待同步' : `${collection.issue_count.toLocaleString()} 条 Issue`}{collection.auto_count != null && ` · 自动 ${collection.auto_count.toLocaleString()} / 人工 ${collection.manual_count?.toLocaleString()}`} · 最近更新：{localTime(collection.synced_at)} · 每 15 分钟检查</p>
          {observing && <p>{t('simFlow.lastIssue')}：{localTime(collection.last_issue_at)}</p>}
          {collection.stale ? <p role="status" className="text-amber-700 dark:text-amber-400">更新延迟，暂展示上次成功采集的数据；恢复完整查询后重新确认收集状态。</p>
            : observing && collection.collection_status === 'collecting' ? <p>{t('simFlow.quietRule')}{collection.eligible_at && <> · {t('simFlow.eligibleAt')}：{localTime(collection.eligible_at)}</>}</p>
            : <p>收集完成与仿真验收分别记录；仿真结果在完成评测后展示。</p>}
        </div> : <p className="w-full text-xs text-muted-foreground">{version === '@stable' ? '暂无已稳定收集的版本，可选择收集中版本查看实时 Issue。' : usesSource ? '路测 Issue 自动同步；选择一条记录查看详情。' : '保留该版本已归档的仿真诊断、筛选与场景详情。'}</p>}
        {notice && <p role="status" className="w-full">{notice}</p>}
        {error && <p role="alert" className="w-full text-destructive">{error}</p>}
      </CardContent>
    </Card>
    {!usesSource && !data ? <p className="text-sm text-muted-foreground">正在查询版本与 Issue…</p> : !usesSource ? history : <div className="grid min-w-0 items-start gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(340px,0.6fr)]">
      <Card className="min-w-0 overflow-hidden">
        <CardHeader><CardTitle>Issue 明细（{total} 条{observing ? ' Issue' : '场景关联记录'}）</CardTitle><p className="break-words text-xs text-muted-foreground">{selectedRelease || '待收集'} · {observing ? '自动及人工触发 Issue；场景与评测结果待仿真流程准备。' : '自动触发路测 Issue；未仿真的结果保持为空。'}</p></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <input aria-label="搜索周期 Issue" placeholder="Issue / Scenario ID / 名称" className="min-w-0 flex-1 rounded border bg-background p-2 text-sm" value={query} onChange={event => { setQuery(event.target.value); setPage(1); }}/>
            {!observing && <input aria-label="场景标签筛选" placeholder="场景 label 精确筛选" className="min-w-0 flex-1 rounded border bg-background p-2 text-sm" value={label} onChange={event => { setLabel(event.target.value); setPage(1); }}/>}
            <Button variant="outline" onClick={() => { setQuery(''); setLabel(''); setPage(1); }}>重置</Button>
          </div>
          <div className="min-w-0 overflow-x-auto"><table className="w-full min-w-[520px] table-fixed text-left text-sm"><colgroup>{[150, 130, 110, 100].map((width, index) => <col key={index} style={{ width }}/>)}</colgroup>
            <thead><tr>{['Issue', 'Scenario', '路测结果', '评测结果'].map(title => <th key={title} className="p-2 text-xs text-muted-foreground">{title}</th>)}</tr></thead>
            <tbody>{rows.map(row => <tr key={rowKey(row)} className={cn('border-t', selected && rowKey(selected) === rowKey(row) && 'bg-primary/5')}>
              <td className="p-2"><button className="text-left font-mono text-primary hover:underline" aria-label={`查看 ${row.issue_id} 详情`} onClick={() => setSelectedKey(rowKey(row))}>{row.issue_id}</button><p className="truncate text-xs text-muted-foreground" title={row.issue_topic}>{row.issue_topic}</p><p className="break-words text-xs text-muted-foreground">{row.road_version}</p></td>
              <td className="p-2">{row.scenario_id || '待匹配'}<p className="truncate text-xs text-muted-foreground" title={row.scenario_name}>{row.scenario_name}</p></td>
              <td className="p-2">{row.source_result || '待确认'}{row.ra_type && <p className="text-xs text-muted-foreground">{row.ra_type === 3 ? '人工触发' : '自动触发'}</p>}</td>
              <td className="p-2">{row.precision_label || '—'}<p className="text-xs text-muted-foreground">{stateNames[row.simulation_status] || row.simulation_status}</p></td>
            </tr>)}{!rows.length && <tr><td colSpan={4} className="p-8 text-center text-muted-foreground">{loading ? '正在查询…' : '暂无匹配 Issue，请检查版本、同步状态或筛选条件。'}</td></tr>}</tbody>
          </table></div>
          <div className="flex flex-wrap items-center justify-end gap-3 text-sm"><Button variant="outline" disabled={page === 1 || loading} onClick={() => setPage(value => value - 1)}>上一页</Button><span>第 {page} / {Math.max(1, Math.ceil(total / 25))} 页</span><Button variant="outline" disabled={page * 25 >= total || loading} onClick={() => setPage(value => value + 1)}>下一页</Button></div>
        </CardContent>
      </Card>
      <Card className="min-w-0 overflow-hidden xl:sticky xl:top-6">
        <CardHeader><div className="flex items-center justify-between gap-3"><CardTitle>{selected?.issue_id || 'Issue 详情'}</CardTitle>{selected && <a className="inline-flex items-center gap-1 text-sm text-primary" href={`https://voyager.intra.xiaojukeji.com/paladin/issue/detail/${encodeURIComponent(selected.issue_id)}`} target="_blank" rel="noreferrer">打开<ExternalLink className="h-3.5 w-3.5"/></a>}</div></CardHeader>
        <CardContent className="space-y-4 text-sm">{selected ? <>
          {selected.issue_topic && <p className="break-words">{selected.issue_topic}</p>}
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2"><dt className="text-muted-foreground">路测构建</dt><dd className="break-all">{selected.road_version}</dd><dt className="text-muted-foreground">路测结果</dt><dd>{selected.source_result || '待确认'}</dd><dt className="text-muted-foreground">仿真状态</dt><dd>{stateNames[selected.simulation_status] || selected.simulation_status}</dd><dt className="text-muted-foreground">仿真触发</dt><dd>{selected.sim_triggered == null ? '—' : selected.sim_triggered ? '触发' : '未触发'}</dd><dt className="text-muted-foreground">评测结果</dt><dd>{selected.precision_label || '—'}</dd></dl>
          {selected.job_id && <p className="text-xs text-muted-foreground">主结果来源：<a className="text-primary hover:underline" target="_blank" rel="noreferrer" href={`http://voyager.intra.xiaojukeji.com/static/management/#/orion/job/detail?job_id=${selected.job_id}`}>Job {selected.job_id}</a>{selected.execution_conflict && ' · 两次执行触发不一致'}</p>}
          {selected.result_note && <details className="rounded border p-3 text-xs"><summary>结果说明</summary><pre className="mt-2 whitespace-pre-wrap break-words">{selected.result_note}</pre></details>}
          <div className="rounded border p-3"><p className="mb-1 font-medium">当前场景 {selected.scenario_id || '待匹配'}</p><p className="break-all text-xs text-muted-foreground">{selected.scenario_name || '尚未匹配场景'}</p>{selected.scenario_id && selectedRelease && <a className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline" href={`${import.meta.env.BASE_URL}simulation?${new URLSearchParams({version: selectedRelease, parameters: '1', scenario: selected.scenario_id})}`}>使用此场景的仿真参数<ExternalLink className="h-3 w-3"/></a>}</div>
          <div><p className="mb-2 font-medium">Scenario labels</p><div className="flex flex-wrap gap-1">{selected.scenario_labels.map(value => <button key={value} title="按此标签筛选" className="max-w-full break-all rounded bg-muted px-2 py-1 text-left text-xs" onClick={() => { setLabel(value); setPage(1); }}>{value}</button>)}{!selected.scenario_labels.length && <span className="text-muted-foreground">暂无真实标签</span>}</div></div>
        </> : <p className="py-8 text-center text-muted-foreground">选择一条 Issue 查看详情。</p>}</CardContent>
      </Card>
    </div>}
  </div>;
}
