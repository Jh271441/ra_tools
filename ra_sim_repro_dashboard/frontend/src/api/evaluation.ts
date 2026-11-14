import { claimEvaluationInitialRead, discardInitialRead, type EvaluationInitialRead, type WireRead } from './initialRead';

const base = `${import.meta.env.BASE_URL.replace(/\/$/, '')}/api/dashboard/evaluation`;
const pendingReads = new Map<string, Promise<unknown>>();
export function evaluationRequest<T>(path: string, method = 'GET', body?: unknown, options: { fresh?: boolean } = {}): Promise<T> {
  const key = base + path;
  if (method === 'GET' && !options.fresh && pendingReads.has(key)) return pendingReads.get(key) as Promise<T>;
  if (method !== 'GET') { discardInitialRead(); pendingReads.clear(); }
  const kind = path.match(/^\/(board|comparison|versions)(?:\?|$)/)?.[1] as EvaluationInitialRead | undefined;
  const early = method === 'GET' && kind ? claimEvaluationInitialRead(kind, key, options.fresh) : undefined;
  const load = async () => {
  const response: WireRead = await (early || fetch(key, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
    .then(async result => ({ ok: result.ok, status: result.status, text: await result.text() })));
  const text = response.text;
  let value;
  try { value = JSON.parse(text); } catch { throw new Error(`HTTP ${response.status}`); }
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : `HTTP ${response.status}`);
  return value as T;
  };
  const task = load();
  if (method === 'GET') { pendingReads.set(key, task); void task.finally(() => { if (pendingReads.get(key) === task) pendingReads.delete(key); }).catch(() => {}); }
  return task;
}
