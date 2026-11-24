import type { HTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

export function FilterPanel({ className, ...props }: HTMLAttributes<HTMLElement>) {
  return (
    <section
      className={cn(
        'apple-panel fine-grid grid min-w-0 gap-3 rounded-lg border bg-card p-3 md:p-4',
        className,
      )}
      {...props}
    />
  );
}
