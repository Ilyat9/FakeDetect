import { cn } from "./lib/cn";

/** Content-shaped skeleton: mirrors the real layout to minimize CLS. */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn("animate-pulse rounded-md bg-neutral-400/20 dark:bg-white/10", className)}
    />
  );
}

export function StatCardSkeleton() {
  return (
    <div className="rounded-xl border border-line bg-surface-raised p-5">
      <Skeleton className="mb-3 h-3 w-24" />
      <Skeleton className="h-12 w-28" />
      <Skeleton className="mt-2 h-3 w-36" />
    </div>
  );
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2" aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}
