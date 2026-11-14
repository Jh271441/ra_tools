import type { EvaluationContext, EvaluationRevision } from '../types/evaluation';

// Sample dates belong to one saved release, while the overview compares releases
// on their own saved scopes. The global release-date filter is applied afterwards.
export function comparisonParams(context: EvaluationContext): URLSearchParams {
  return new URLSearchParams(context.profile_id ? { profile_id: context.profile_id } : {});
}

export function changeEvaluationRelease(context: EvaluationContext, release: string): EvaluationContext {
  if (context.release === release) return context;
  const { date_start: _start, date_end: _end, ...shared } = context;
  return { ...shared, release, date_start: undefined, date_end: undefined };
}

export function changeEvaluationReleaseQuery(query: URLSearchParams, release: string): URLSearchParams {
  const next = new URLSearchParams(query);
  const previous = next.get('release') || next.get('version') || '@current';
  if (previous !== release) {
    next.delete('date_start'); next.delete('date_end'); next.set('page', '1');
  }
  if (release === '@current') {
    next.delete('release'); next.delete('version');
  } else {
    next.set('release', release); next.set('version', release);
  }
  return next;
}

export function validEvaluationDates(context: EvaluationContext): boolean {
  return (!context.date_start && !context.date_end) ||
    Boolean(context.date_start && context.date_end && context.date_start <= context.date_end);
}

export function comparisonRevisions(revisions: EvaluationRevision[], selected: EvaluationRevision): EvaluationRevision[] {
  const others = revisions.filter(revision => revision.context.release !== selected.context.release);
  return [...others, selected].sort((left, right) => left.context.release.localeCompare(right.context.release));
}

// An empty current release must not hide already verified history. Keep the
// requested context unchanged; the caller labels the saved scope explicitly.
export function overviewRevision(selected: EvaluationRevision | null | undefined, stale: boolean,
  revisions: EvaluationRevision[], visibleReleases?: string[]): EvaluationRevision | undefined {
  const visible = (value: EvaluationRevision) => !visibleReleases || visibleReleases.includes(value.context.release);
  if (selected && !stale && visible(selected)) return selected;
  return revisions.filter(visible).sort((left, right) => right.context.release.localeCompare(left.context.release))[0];
}
