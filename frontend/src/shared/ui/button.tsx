import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "./lib/cn";

type Variant = "primary" | "secondary" | "danger" | "ghost";
type Size = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  children: ReactNode;
}

const VARIANTS: Record<Variant, string> = {
  primary: "bg-verdict-fake text-white hover:bg-verdict-fake/85",
  secondary:
    "bg-surface-raised text-ink border border-line hover:bg-surface-light dark:hover:bg-surface-dark",
  danger: "bg-red-600 text-white hover:bg-red-500",
  ghost: "text-ink-muted hover:text-ink hover:bg-surface-light dark:hover:bg-surface-dark",
};

const SIZES: Record<Size, string> = {
  sm: "px-2.5 py-1 text-xs",
  md: "px-4 py-2 text-sm",
};

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  className,
  disabled,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-lg font-semibold transition-colors",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-verdict-info",
        "disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      disabled={disabled ?? loading}
      aria-busy={loading}
      {...rest}
    >
      {loading && (
        <span
          aria-hidden
          className="size-3 animate-spin rounded-full border-2 border-current border-t-transparent"
        />
      )}
      {children}
    </button>
  );
}
