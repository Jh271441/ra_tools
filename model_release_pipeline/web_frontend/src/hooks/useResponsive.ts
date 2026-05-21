import { useEffect, useState } from 'react';

export type Breakpoint = 'mobile' | 'tablet' | 'desktop';

const MOBILE = 640;
const TABLET = 860;

function getBreakpoint(): Breakpoint {
  const w = window.innerWidth;
  if (w < MOBILE) return 'mobile';
  if (w < TABLET) return 'tablet';
  return 'desktop';
}

export function useResponsive() {
  const [bp, setBp] = useState<Breakpoint>(getBreakpoint);

  useEffect(() => {
    const handler = () => setBp(getBreakpoint());
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);

  return {
    breakpoint: bp,
    isMobile: bp === 'mobile',
    isTablet: bp === 'tablet',
    isDesktop: bp === 'desktop',
    isMobileOrTablet: bp !== 'desktop',
  };
}
