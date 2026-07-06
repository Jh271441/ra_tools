import type { ButtonHTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

type ButtonVariant = 'default' | 'secondary' | 'outline' | 'ghost';
type ButtonSize = 'sm' | 'md' | 'icon';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

const variants: Record<ButtonVariant, string> = {
  default: 'bg-primary text-primary-foreground shadow-[0_8px_18px_hsl(var(--primary)/0.2)] hover:bg-primary/90 dark:shadow-[0_8px_22px_hsl(var(--primary)/0.16)]',
  secondary: 'bg-accent text-accent-foreground hover:bg-accent/80 dark:bg-accent/70',
  outline: 'border border-input bg-card/70 shadow-sm backdrop-blur hover:border-ring/50 hover:bg-accent hover:text-accent-foreground dark:bg-card/60 dark:hover:bg-accent/70',
  ghost: 'hover:bg-accent hover:text-accent-foreground dark:hover:bg-accent/60',
};

const sizes: Record<ButtonSize, string> = {
  sm: 'h-8 rounded-md px-3 text-xs',
  md: 'h-9 rounded-md px-3 text-sm',
  icon: 'h-9 w-9 rounded-md p-0',
};

export function Button({ className, variant = 'default', size = 'md', ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        'inline-flex shrink-0 items-center justify-center gap-2 font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50',
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    />
  );
}
