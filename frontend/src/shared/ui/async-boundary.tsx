import { isApiError } from "@/shared/api/errors";
import type { ReactNode } from "react";

import { Button } from "./button";

interface AsyncBoundaryProps {
  loading: boolean;
  error: unknown;
  isEmpty?: boolean;
  onRetry?: () => void;
  /** Content-shaped skeleton shown while loading (minimizes CLS). */
  loadingFallback: ReactNode;
  emptyFallback?: ReactNode;
  children: ReactNode;
}

/**
 * Unified async screen states (loading / error / empty / success) —
 * one reusable pattern instead of hand-rolled `if (loading)...` in every page.
 */
export function AsyncBoundary({
  loading,
  error,
  isEmpty = false,
  onRetry,
  loadingFallback,
  emptyFallback,
  children,
}: AsyncBoundaryProps) {
  if (loading) {
    return <>{loadingFallback}</>;
  }

  if (error) {
    const message =
      isApiError(error) && error.requestId
        ? `${error.message} (request_id: ${error.requestId})`
        : isApiError(error)
          ? error.message
          : "Неизвестная ошибка загрузки данных";
    return (
      <div
        role="alert"
        className="rounded-xl border border-verdict-fake/40 bg-verdict-fake/5 p-6 text-center"
      >
        <p className="font-display text-xl tracking-wide text-verdict-fake">Ошибка загрузки</p>
        <p className="mt-1 text-sm text-ink-muted">{message}</p>
        {onRetry && (
          <Button variant="secondary" size="sm" className="mt-4" onClick={onRetry}>
            Повторить
          </Button>
        )}
      </div>
    );
  }

  if (isEmpty) {
    return (
      emptyFallback ?? (
        <EmptyState title="Пока ничего нет" hint="Данные появятся здесь после первых проверок." />
      )
    );
  }

  return <>{children}</>;
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-line p-10 text-center">
      {/* Inline SVG illustration — no external asset needed. */}
      <svg aria-hidden viewBox="0 0 64 64" className="mb-4 size-16 text-neutral-400/50 dark:text-white/20" fill="currentColor">
        <path d="M32 4a28 28 0 1 0 28 28A28 28 0 0 0 32 4zm0 8a20 20 0 0 1 12.3 4.2L18.2 44.3A20 20 0 0 1 32 12zm0 40a19.9 19.9 0 0 1-12.3-4.2l26.1-28.1A20 20 0 0 1 32 52z" />
      </svg>
      <p className="font-display text-2xl tracking-wide">{title}</p>
      <p className="mt-1 max-w-sm text-sm text-ink-muted">{hint}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
