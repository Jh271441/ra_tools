import { Panel, useReactFlow, useStore } from '@xyflow/react';
import { useEffect } from 'react';
import { Maximize, Minus, Plus } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from './ui/button';

export function FlowControls() {
  const { t } = useTranslation();
  const { zoomIn, zoomOut, fitView } = useReactFlow();
  const width = useStore((state) => state.width),
    height = useStore((state) => state.height);
  // Caption nodes have no handles. Track measured geometry directly so those
  // labels cannot keep the all-handles initialization hook pending forever.
  // Receipt/status updates do not change this key or reset a user's viewport.
  const geometry = useStore((state) =>
    Array.from(state.nodeLookup.values())
      .filter((node) => !node.hidden)
      .map((node) =>
        [
          node.id,
          node.position.x,
          node.position.y,
          node.measured?.width || node.width || 0,
          node.measured?.height || node.height || 0,
        ].join(':'),
      )
      .join('|'),
  );
  useEffect(() => {
    if (!geometry || !width || !height) return;
    const frame = requestAnimationFrame(() => void fitView({ padding: 0.08, maxZoom: 1 }));
    return () => cancelAnimationFrame(frame);
  }, [width, height, geometry, fitView]);
  return (
    <Panel position="top-right" className="sim-flow-controls">
      <Button
        variant="outline"
        size="icon"
        aria-label={t('simFlow.zoomIn')}
        title={t('simFlow.zoomIn')}
        onClick={() => void zoomIn()}
      >
        <Plus size={17} />
      </Button>
      <Button
        variant="outline"
        size="icon"
        aria-label={t('simFlow.zoomOut')}
        title={t('simFlow.zoomOut')}
        onClick={() => void zoomOut()}
      >
        <Minus size={17} />
      </Button>
      <Button
        variant="outline"
        size="icon"
        aria-label={t('simFlow.fit')}
        title={t('simFlow.fit')}
        onClick={() => void fitView({ padding: 0.08, maxZoom: 1 })}
      >
        <Maximize size={17} />
      </Button>
    </Panel>
  );
}
