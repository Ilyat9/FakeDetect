import { useEffect, useRef, type ReactNode } from "react";

import { cn } from "./lib/cn";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  /** Rendered as a destructive action area (e.g. confirm modals). */
  tone?: "default" | "danger";
}

/**
 * Accessible modal: focus trap basics (focus moved into dialog on open and
 * restored on close), Escape to dismiss, click-outside backdrop.
 * Built on native semantics instead of div-onclick hacks.
 */
export function Dialog({ open, onClose, title, tone = "default", children }: DialogProps) {
  const ref = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    const firstFocusable = ref.current?.querySelector<HTMLElement>(
      "button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])",
    );
    firstFocusable?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previouslyFocused.current?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn(
          "w-full max-w-md rounded-xl border border-line bg-surface-raised p-6 shadow-xl dark:bg-surface-raised",
          tone === "danger" && "border-verdict-fake/60",
        )}
      >
        <h2 className="mb-4 font-display text-2xl tracking-wide">{title}</h2>
        {children}
      </div>
    </div>
  );
}
