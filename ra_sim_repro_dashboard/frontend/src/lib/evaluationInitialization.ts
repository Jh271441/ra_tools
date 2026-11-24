import type { EvaluationBoard, EvaluationContext } from '../types/evaluation';

type SavedEvaluationRequest = EvaluationContext & { refresh_labels: false };

export function savedEvaluationInitializationKey(board: EvaluationBoard | null): string | null {
  if (
    !board ||
    board.revision ||
    board.stale ||
    board.sample_source.status !== 'ready' ||
    !board.sample_source.snapshot_id ||
    board.profile.status !== 'published' ||
    board.cron.processing_enabled === false ||
    ['queued', 'running', 'failed'].includes(board.refresh.status || '')
  )
    return null;
  const context = board.context;
  if (
    !context.release ||
    !context.profile_id ||
    !context.date_start ||
    !context.date_end ||
    context.date_start > context.date_end
  )
    return null;
  return JSON.stringify([
    context.release,
    context.profile_id,
    context.date_start,
    context.date_end,
    board.sample_source.snapshot_id,
  ]);
}

// A saved date range needs its own projection, even when another range of the
// same release already has metrics. Only evaluate persisted data: this request
// cannot acquire samples, prepare scenarios, or start a simulation.
export function createSavedEvaluationInitializer(
  enqueue: (body: SavedEvaluationRequest) => Promise<unknown>,
) {
  const attempts = new Map<string, Promise<unknown>>();
  return (board: EvaluationBoard): Promise<unknown> | null => {
    const key = savedEvaluationInitializationKey(board);
    if (!key) return null;
    if (!attempts.has(key)) {
      const body: SavedEvaluationRequest = { ...board.context, refresh_labels: false };
      attempts.set(
        key,
        Promise.resolve().then(() => enqueue(body)),
      );
    }
    // Share the same attempt across rerenders and StrictMode subscriptions.
    // A failed attempt is retried only by the explicit retry/recalculate action.
    return attempts.get(key)!;
  };
}
