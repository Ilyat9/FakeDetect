import type { ReactNode } from "react";

import { cn } from "./lib/cn";

interface TabsProps {
  tabs: readonly { id: string; label: string }[];
  activeId: string;
  onChange: (id: string) => void;
  children?: ReactNode;
}

export function Tabs({ tabs, activeId, onChange, children }: TabsProps) {
  return (
    <div>
      <div role="tablist" aria-label="Режим ввода" className="flex gap-1 rounded-lg border border-line bg-surface p-1">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={activeId === t.id}
            onClick={() => { onChange(t.id); }}
            className={cn(
              "flex-1 rounded-md px-3 py-2 text-sm font-semibold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-verdict-info",
              activeId === t.id
                ? "bg-verdict-fake text-white"
                : "text-ink-muted hover:text-ink",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      {children}
    </div>
  );
}
