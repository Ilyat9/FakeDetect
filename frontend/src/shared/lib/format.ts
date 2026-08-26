const RU_DATE_FMT = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

const RU_DATETIME_FMT = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatDate(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const d = typeof value === "string" ? new Date(value) : value;
  return Number.isNaN(d.getTime()) ? "—" : RU_DATE_FMT.format(d);
}

export function formatDateTime(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const d = typeof value === "string" ? new Date(value) : value;
  return Number.isNaN(d.getTime()) ? "—" : RU_DATETIME_FMT.format(d);
}

export function formatNumber(value: number | null | undefined): string {
  return new Intl.NumberFormat("ru-RU").format(value ?? 0);
}

export function formatCurrency(value: number | null | undefined, currency = "RUB"): string {
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(value ?? 0);
}

export function formatPercent(value: number | null | undefined, digits = 1): string {
  return `${(value ?? 0).toFixed(digits)}%`;
}

/** "3 дн 4 ч назад"-style relative label for timelines/SLA badges. */
export function formatDuration(ms: number): string {
  const abs = Math.abs(ms);
  const minutes = Math.floor(abs / 60_000);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  if (days > 0) return `${days} дн`;
  if (hours > 0) return `${hours} ч`;
  if (minutes > 0) return `${minutes} мин`;
  return "< 1 мин";
}

/** Frequency presets -> cron expression so users never write cron by hand. */
export type ScheduleFrequency = "daily" | "weekly";

export const SCHEDULE_PRESETS: Record<ScheduleFrequency, string> = {
  daily: "0 7 * * *",
  weekly: "0 7 * * 1",
};
