export interface WireRead { ok: boolean; status: number; text: string }
export interface InitialRead {
  claimed?: boolean;
  url?: string;
  startedAt?: number;
  read?: Promise<WireRead>;
}
export type EvaluationInitialRead = 'board' | 'comparison' | 'versions';
export interface StartupReads extends InitialRead { evaluation?: Partial<Record<EvaluationInitialRead, InitialRead>> }
declare global { interface Window { __RA_SIM_STARTUP__?: StartupReads } }

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
export function claimEvaluationInitialRead(kind: EvaluationInitialRead, url: string, fresh = false) {
  const state = window.__RA_SIM_STARTUP__ ||= {};
  const evaluation = state.evaluation ||= {};
  return takeInitialRead(evaluation[kind] ||= {}, url, fresh);
}
export function discardInitialRead() {
  const state = window.__RA_SIM_STARTUP__ ||= {};
  takeInitialRead(state, '', true);
  for (const kind of ['board', 'comparison', 'versions'] as const) {
    const evaluation = state.evaluation ||= {};
    takeInitialRead(evaluation[kind] ||= {}, '', true);
  }
}
