export interface WireRead { ok: boolean; status: number; text: string }
export interface InitialRead {
  claimed?: boolean;
  url?: string;
  startedAt?: number;
  read?: Promise<WireRead>;
}
declare global { interface Window { __RA_SIM_STARTUP__?: InitialRead } }

/** One use only: neither a different version nor a fresh read may reuse startup data. */
export function takeInitialRead(state: InitialRead, url: string, fresh = false, now = Date.now()): Promise<WireRead> | undefined {
  const read = state.read;
  delete state.read;
  state.claimed = true;
  const age = now - (state.startedAt ?? -Infinity);
  if (fresh || state.url !== url || age < 0 || age >= 15_000) return;
  return read;
}

export function claimInitialRead(url: string, fresh = false) {
  return takeInitialRead(window.__RA_SIM_STARTUP__ ||= {}, url, fresh);
}
export function discardInitialRead() {
  takeInitialRead(window.__RA_SIM_STARTUP__ ||= {}, '', true);
}
