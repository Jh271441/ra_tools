/** Short-lived display snapshots. Every selection must be verified before writes. */
export class ViewCache<T> {
  private values = new Map<string, { data: T; signature: string; savedAt: number }>();
  private ttl: number;
  private limit: number;
  private now: () => number;
  constructor(ttl = 120_000, limit = 8, now = Date.now) { this.ttl = ttl; this.limit = limit; this.now = now; }

  get(key: string): T | null {
    const value = this.values.get(key);
    if (!value || this.now() - value.savedAt >= this.ttl) {
      this.values.delete(key);
      return null;
    }
    return value.data;
  }

  put(key: string, data: T): T {
    const signature = JSON.stringify(data);
    const previous = this.values.get(key);
    const stable = previous?.signature === signature ? previous.data : data;
    this.values.delete(key);
    this.values.set(key, { data: stable, signature, savedAt: this.now() });
    while (this.values.size > this.limit) this.values.delete(this.values.keys().next().value!);
    return stable;
  }

  clear() { this.values.clear(); }
}

interface ViewState<T> {
  key: string;
  data: T | null;
  verified: boolean;
  loading: boolean;
  error: string;
}

export interface ReadOptions { fresh?: boolean; force?: boolean }

/** Owns selection/request races as well as the write guard for cached displays. */
export class LiveView<T> {
  private state: ViewState<T>;
  private generation = 0;
  private pending: Promise<T | null> | null = null;
  private listeners = new Set<() => void>();
  private cache: ViewCache<T>;
  private loader: (key: string, options: ReadOptions) => Promise<T>;

  constructor(key: string, cache: ViewCache<T>, loader: (key: string, options: ReadOptions) => Promise<T>) {
    this.cache = cache;
    this.loader = loader;
    this.state = { key, data: cache.get(key), verified: false, loading: false, error: '' };
  }

  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  private update(next: ViewState<T>) {
    if (Object.keys(next).every(key => next[key as keyof ViewState<T>] === this.state[key as keyof ViewState<T>])) return;
    this.state = next;
    this.listeners.forEach(listener => listener());
  }

  select(key: string) {
    if (key === this.state.key) return;
    this.cancel();
    this.update({ key, data: this.cache.get(key), verified: false, loading: false, error: '' });
  }

  cancel = () => { this.generation++; this.pending = null; };

  invalidate() {
    this.cancel();
    this.cache.clear();
    this.update({ ...this.state, verified: false });
  }

  reload = (options: ReadOptions = {}): Promise<T | null> => {
    if (this.pending && !options.fresh && !options.force) return this.pending;
    const id = ++this.generation;
    const key = this.state.key;
    this.update({ ...this.state, loading: true });
    const task = (async () => {
      try {
        const result = await Promise.resolve().then(() => this.loader(key, options));
        if (id !== this.generation) return null;
        const data = this.cache.put(key, result);
        this.update({ key, data, verified: true, loading: false, error: '' });
        return data;
      } catch (error) {
        if (id === this.generation) this.update({ ...this.state, loading: false, verified: false, error: error instanceof Error ? error.message : String(error) });
        return null;
      } finally {
        if (id === this.generation) this.pending = null;
      }
    })();
    this.pending = task;
    return task;
  };
}

interface PollEnvironment {
  hidden: () => boolean;
  listen: (callback: () => void) => () => void;
  schedule: (callback: () => void, delay: number) => unknown;
  clear: (timer: unknown) => void;
}

/** One request at a time; resume immediately on visibility, with bounded fast polling. */
export function pollVisible<T>(load: () => Promise<T | null>, refreshing: (value: T) => boolean, env: PollEnvironment) {
  let stopped = false;
  let running = false;
  let fastReads = 0;
  let timer: unknown;
  const clear = () => { if (timer !== undefined) { env.clear(timer); timer = undefined; } };
  const tick = async () => {
    if (stopped || env.hidden()) return;
    if (running) return;
    running = true;
    const value = await load();
    running = false;
    if (stopped || env.hidden()) return;
    const fast = value != null && refreshing(value) && fastReads < 3;
    fastReads = fast ? fastReads + 1 : value && !refreshing(value) ? 0 : fastReads;
    timer = env.schedule(() => { timer = undefined; void tick(); }, fast ? 5_000 : 30_000);
  };
  const unlisten = env.listen(() => {
    clear();
    if (!env.hidden()) void tick();
  });
  void tick();
  return () => { stopped = true; clear(); unlisten(); };
}
