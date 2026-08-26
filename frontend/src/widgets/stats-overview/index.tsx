import type { StatsOverview } from "@/entities/check/types";
import { StatCardSkeleton } from "@/shared/ui/skeletons";
import { formatNumber } from "@/shared/lib/format";

interface StatsOverviewWidgetProps {
  stats: StatsOverview | undefined;
}

const FAKE_METHODOLOGY =
  "«Защищённая выручка» = Σ (цена подозрительной карточки × количество подтверждённых подделок). Оценка потенциального ущерба, предотвращённого снятием карточек; не является бухгалтерской метрикой.";

/** Four overview counters of the dashboard (spec 5.1). */
export function StatsOverviewWidget({ stats }: StatsOverviewWidgetProps) {
  if (!stats) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <StatCardSkeleton key={i} />
        ))}
      </div>
    );
  }

  const cards = [
    { label: "Подделок выявлено", value: stats.fakes, color: "text-verdict-fake", border: "bg-verdict-fake" },
    { label: "Оригиналов подтверждено", value: stats.originals, color: "text-verdict-original", border: "bg-verdict-original" },
    { label: "Под вопросом", value: stats.suspicious, color: "text-verdict-suspect", border: "bg-verdict-suspect" },
    { label: "Всего проверок", value: stats.total, color: "text-verdict-info", border: "bg-verdict-info" },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map((c) => (
        <div
          key={c.label}
          className="relative overflow-hidden rounded-xl border border-line bg-surface-raised p-5"
        >
          <span aria-hidden className={`absolute inset-y-0 left-0 w-1 ${c.border}`} />
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.15em] text-ink-muted">
            {c.label}
          </p>
          <p className={`font-display text-5xl leading-none ${c.color}`}>{formatNumber(c.value)}</p>
          {c.label.startsWith("Всего") && (
            <p title={FAKE_METHODOLOGY} className="mt-2 cursor-help text-xs text-ink-muted underline decoration-dotted">
              Методология расчёта метрик
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
