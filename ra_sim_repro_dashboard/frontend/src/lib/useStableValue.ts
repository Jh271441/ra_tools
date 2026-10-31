import { useMemo } from 'react';

/** API polling produces fresh objects even when a small graph projection is unchanged. */
export function useStableValue<T>(value: T): T {
  const signature = JSON.stringify(value);
  return useMemo(() => value, [signature]);
}
