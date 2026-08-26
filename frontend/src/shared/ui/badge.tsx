import type { ReactNode } from "react";

import { cn } from "./lib/cn";

type Tone = "fake" | "original" | "suspect" | "info" | "neutral" | "purple";

const TONES: Record<Tone, string> = {
  fake: "bg-verdict-fake text-white",
  original: "bg-verdict-original text-white",
  suspect: "bg-verdict-suspect text-black",
  info: "bg-verdict-info text-white",
  purple: "bg-purple-500 text-white",
  neutral: "bg-neutral-400/80 text-white",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
        TONES[tone],
      )}
    >
      {children}
    </span>
  );
}
