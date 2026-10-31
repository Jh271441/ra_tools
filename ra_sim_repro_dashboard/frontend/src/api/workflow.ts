import { claimInitialRead, discardInitialRead, type WireRead } from './initialRead';

const base = `${import.meta.env.BASE_URL.replace(/\/$/, '')}/api/dashboard/workflow`;
const pendingReads = new Map<string, Promise<unknown>>();

export function request<T>(path = '', method = 'GET', body?: unknown, options: { fresh?: boolean } = {}): Promise<T> {
  const key = base + path;
  const pending = method === 'GET' && !options.fresh ? pendingReads.get(key) : undefined;
  if (pending) return pending as Promise<T>;
  if (method !== 'GET') discardInitialRead();
  const early = method === 'GET' && path.startsWith('/board?') ? claimInitialRead(key, options.fresh) : undefined;
  const load = async () => {
    const response: WireRead = await (early || fetch(key, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
      .then(async result => ({ ok: result.ok, status: result.status, text: await result.text() })));
    // Gateways may return HTML on a timeout; never expose an HTML parser error.
    const text = response.text;
    let data;
    try { data = JSON.parse(text); }
    catch { throw new Error(`HTTP ${response.status}`); }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${response.status}`);
    return data as T;
  };
  const result = load();
  if (method === 'GET') {
    pendingReads.set(key, result);
    void result.finally(() => { if (pendingReads.get(key) === result) pendingReads.delete(key); }).catch(() => {});
  }
  return result;
}
