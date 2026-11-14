const base = `${import.meta.env.BASE_URL.replace(/\/$/, '')}/api/dashboard/evaluation`;
const pendingReads = new Map<string, Promise<unknown>>();
export function evaluationRequest<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const key = base + path;
  if (method === 'GET' && pendingReads.has(key)) return pendingReads.get(key) as Promise<T>;
  const load = async () => {
  const response = await fetch(key, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await response.text();
  let value;
  try { value = JSON.parse(text); } catch { throw new Error(`HTTP ${response.status}`); }
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : `HTTP ${response.status}`);
  return value as T;
  };
  const task = load();
  if (method === 'GET') { pendingReads.set(key, task); void task.finally(() => { if (pendingReads.get(key) === task) pendingReads.delete(key); }).catch(() => {}); }
  return task;
}
