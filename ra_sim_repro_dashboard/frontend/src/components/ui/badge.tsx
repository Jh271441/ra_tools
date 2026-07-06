import type { HTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

type BadgeVariant = 'default' | 'secondary' | 'success' | 'warning' | 'destructive' | 'outline';

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

const variants: Record<BadgeVariant, string> = {
  default: 'border-transparent bg-primary text-primary-foreground shadow-sm shadow-primary/20',
  secondary: 'border-transparent bg-accent text-accent-foreground dark:bg-accent/70',
  success: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:border-primary/30 dark:bg-primary/10 dark:text-primary',
  warning: 'border-amber-500/25 bg-amber-500/10 text-amber-700 dark:text-amber-300',
  destructive: 'border-red-500/25 bg-red-500/10 text-red-700 dark:text-red-300',
  outline: 'border-border/80 bg-card/50 text-foreground dark:bg-white/[0.03]',
};

export function Badge({ className, variant = 'outline', ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-semibold',
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}
