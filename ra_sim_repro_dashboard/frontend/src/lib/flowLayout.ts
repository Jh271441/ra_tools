export const retryGeometry = {
  collectOut: 0.7,
  collectReturn: 0.3,
  backfillX: 270,
  backfillPitch: 160,
  backfillWidth: 136,
  backfillHeight: 104,
  leftRail: -36,
};

/** Main recovery and label feedback remain visible and connected above AutoTriage. */
export function flowLayout(auto: boolean, backfill: boolean, labels: boolean) {
  let next = 280;
  const backfillY = backfill ? next : undefined;
  if (backfillY != null) next += 200;
  const labelY = labels ? next : undefined;
  if (labelY != null) next += 220;
  return {
    mainY: 40,
    autoY: next,
    backfillY,
    labelY,
    height: auto
      ? next + 202
      : labelY != null
        ? labelY + 186
        : backfillY != null
          ? backfillY + 164
          : 256,
  };
}

export function mainRetryConnections(
  layout: ReturnType<typeof flowLayout>,
  motion: {
    labelActive: boolean;
    labelScheduled: boolean;
    recoveryActive: boolean;
    recoveryScheduled: boolean;
  },
) {
  const links = [];
  if (layout.backfillY != null)
    links.push(
      {
        id: 'prepare-backfill',
        source: 'prepare',
        sourceHandle: 'recovery-out',
        target: 'backfill-sync',
        targetHandle: 'branch-in',
        animated: motion.recoveryActive,
        data: { scheduled: motion.recoveryScheduled },
      },
      {
        id: 'backfill-verify',
        source: 'backfill-merge',
        sourceHandle: 'branch-out',
        target: 'verify',
        targetHandle: 'recovery-in',
        animated: motion.recoveryActive,
        data: { scheduled: motion.recoveryScheduled },
      },
    );
  if (layout.labelY != null)
    links.push(
      {
        id: 'collect-label-sync',
        source: 'collect',
        sourceHandle: 'branch-out',
        target: 'label-sync',
        targetHandle: 'branch-in',
        animated: motion.labelActive,
        data: { scheduled: motion.labelScheduled },
      },
      {
        id: 'label-apply-collect',
        source: 'label-apply',
        sourceHandle: 'branch-out',
        target: 'collect',
        targetHandle: 'branch-return',
        animated: motion.labelActive,
        data: {
          scheduled: motion.labelScheduled,
          returnLane: true,
          loopY: layout.labelY + 146,
          loopX: retryGeometry.leftRail,
        },
      },
    );
  return links;
}

export function returnPath(sx: number, sy: number, tx: number, ty: number, lx: number, ly: number) {
  return `M ${sx} ${sy} L ${sx} ${ly - 6} Q ${sx} ${ly} ${sx - 6} ${ly} L ${lx + 6} ${ly} Q ${lx} ${ly} ${lx} ${ly - 6} L ${lx} ${ty + 28} Q ${lx} ${ty + 22} ${lx + 6} ${ty + 22} L ${tx - 6} ${ty + 22} Q ${tx} ${ty + 22} ${tx} ${ty + 16} L ${tx} ${ty}`;
}

/** A return or reuse link stays in the gutter immediately below its own lane. */
export function lanePath(sx: number, sy: number, tx: number, ty: number, y: number) {
  const r = Math.min(6, Math.abs(tx - sx) / 2, Math.max(0, y - Math.max(sy, ty)) / 2);
  const direction = Math.sign(tx - sx) || 1;
  return `M ${sx} ${sy} L ${sx} ${y - r} Q ${sx} ${y} ${sx + direction * r} ${y} L ${tx - direction * r} ${y} Q ${tx} ${y} ${tx} ${y - r} L ${tx} ${ty}`;
}
