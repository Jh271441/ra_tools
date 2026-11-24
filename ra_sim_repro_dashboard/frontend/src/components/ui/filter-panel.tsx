import type { HTMLAttributes } from "react";
import { cn } from "../../lib/utils";

export function FilterPanel({
  className,
  ...props
}: HTMLAttributes<HTMLElement>) {
  return (
    <section
      className={cn(
        "apple-panel grid min-w-0 gap-3 rounded-lg border bg-card p-3.5 md:p-4",
        className,
      )}
      {...props}
    />
  );
}
