import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "./lib/cn";

export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-xl border border-line bg-surface-raised p-5 shadow-sm dark:border-line dark:bg-surface-raised",
        className,
      )}
      {...rest}
    />
  );
}

export function CardTitle({ children }: { children: ReactNode }) {
  return (
    <h3 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.2em] text-ink-muted">
      {children}
    </h3>
  );
}
