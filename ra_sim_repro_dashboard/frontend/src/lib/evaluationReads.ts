import type { EvaluationContext } from '../types/evaluation';

export function evaluationParams(context: EvaluationContext): URLSearchParams {
  return new URLSearchParams((['release', 'profile_id', 'date_start', 'date_end'] as const)
    .filter(key => context[key]).map(key => [key, context[key]!]));
}

export function evaluationScope(context: EvaluationContext): string {
  return evaluationParams(context).toString();
}

/** A retained history can survive date/release navigation, but never a rule change. */
export function matchingComparison<T extends { profile: { id: string } }>(result: { requestedProfile?: string; value: T } | null, profile?: string): T | undefined {
  return result && (profile ? result.value.profile.id === profile : !result.requestedProfile) ? result.value : undefined;
}

/** The default profile may become explicit after board canonicalization. Reuse it
 * only when the comparison itself proves that it resolved to the same profile. */
export function createComparisonReader<T extends { profile: { id: string } }>(load: (profile?: string) => Promise<T>, now = Date.now) {
  let previous: { profile?: string; attempt: number; startedAt: number; task: Promise<T> } | undefined;
  return (profile: string | undefined, attempt: number): Promise<T> => {
    if (previous && previous.attempt === attempt && now() - previous.startedAt >= 0 && now() - previous.startedAt < 30_000) {
      if (previous.profile === profile) return previous.task;
      if (!previous.profile && profile) {
        const saved = previous;
        const task = saved.task.then(value => {
          if (value.profile.id === profile) return value;
          return load(profile);
        });
        previous = { profile, attempt, task, startedAt: saved.startedAt };
        return task;
      }
    }
    const task = load(profile);
    previous = { profile, attempt, task, startedAt: now() };
    return task;
  };
}

/** Initial board hydration establishes a baseline. Only a later accepted revision
 * change for the same saved scope invalidates the comparison. */
export function createRevisionObserver() {
  const revisions = new Map<string, string | null>();
  return (context: EvaluationContext, revision: string | null): boolean => {
    const scope = evaluationScope(context);
    const changed = revisions.has(scope) && revisions.get(scope) !== revision;
    revisions.set(scope, revision);
    return changed;
  };
}
