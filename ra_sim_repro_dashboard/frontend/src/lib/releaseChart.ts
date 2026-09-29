/** Each release owns one equal interval; its index is the interval's centre. */
export function releaseChartRows<T extends { version_key: string }>(rows: T[]) {
  return rows.map((row, releaseIndex) => ({ ...row, releaseIndex }));
}

function shortVersion(key: string) {
  const separated = key.match(/(?:^|[-_])(\d{4})[-_](\d{2})[-_](\d{2})/);
  if (separated) return `${separated[2]}-${separated[3]}`;
  const compact = key.match(/(\d{8})/);
  if (compact) return `${compact[1].slice(4, 6)}-${compact[1].slice(6, 8)}`;
  return key.length > 10 ? key.slice(-10) : key;
}

export function releaseXAxis(rows: Array<{ version_key: string }>) {
  const labelInterval = Math.max(1, Math.ceil(rows.length / 12));
  return {
    dataKey: 'releaseIndex',
    type: 'number' as const,
    scale: 'linear' as const,
    // Half an interval at each edge keeps the first and last release centred.
    domain: [-0.5, Math.max(1, rows.length) - 0.5] as [number, number],
    ticks: rows.map((_, index) => index),
    interval: labelInterval - 1,
    tickFormatter: (index: number) => shortVersion(rows[index]?.version_key ?? ''),
    padding: { left: 12, right: 12 },
    height: 30,
    tickMargin: 8,
    minTickGap: 0,
    axisLine: false,
    tickLine: false,
    tick: { fontSize: 11, fill: 'hsl(var(--muted-foreground))', textAnchor: 'middle' as const },
  };
}

/** Both charts anchor their cursor and tooltip to the same release coordinate. */
export const releaseTooltip = {
  offset: 12,
  isAnimationActive: false,
  reverseDirection: { x: false, y: false },
  allowEscapeViewBox: { x: false, y: false },
  cursor: {
    stroke: 'hsl(var(--primary) / 0.35)',
    strokeWidth: 1.5,
    strokeDasharray: '4 6',
    pointerEvents: 'none' as const,
  },
};
