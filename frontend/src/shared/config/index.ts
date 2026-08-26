/**
 * Runtime configuration. The only place that reads import.meta.env —
 * no component may hardcode API URLs.
 */
export const API_URL: string = import.meta.env.VITE_API_URL ?? "/api/v1";

export const APP_NAME = "FakeDetect";

export const THEME_STORAGE_KEY = "fakedetect-theme";
/** UI preference only (collapsed sidebar) — no sensitive data here. */
export const SIDEBAR_STORAGE_KEY = "fakedetect-sidebar-collapsed";

export const MARKETPLACES = ["WB", "OZON", "YM"] as const;
export type Marketplace = (typeof MARKETPLACES)[number];

export const MARKETPLACE_LABELS: Record<Marketplace, string> = {
  WB: "Wildberries",
  OZON: "Ozon",
  YM: "Яндекс Маркет",
};

/**
 * LLM providers supported by the backend (core/config.py).
 * Shown explicitly in the analyze form so the user understands
 * fast vs deep analysis trade-offs.
 */
export type ProviderId = "gemini" | "grok";

export interface ProviderInfo {
  id: ProviderId;
  label: string;
  hint: string;
}

export const PROVIDERS: readonly ProviderInfo[] = [
  {
    id: "gemini",
    label: "Gemini 2.5 Flash Vision",
    hint: "Баланс скорости и качества; бесплатная квота Google AI Studio.",
  },
  {
    id: "grok",
    label: "Grok Vision",
    hint: "Альтернативный провайдер; используйте как fallback или для консенсуса.",
  },
] as const;

/** Case workflow status machine (mirrors routers/cases.py). */
export const CASE_STATUSES = [
  "DETECTED",
  "UNDER_REVIEW",
  "CONFIRMED_FAKE",
  "FALSE_POSITIVE",
  "COMPLAINT_FILED",
  "LISTING_REMOVED",
  "CLOSED",
] as const;
export type CaseStatus = (typeof CASE_STATUSES)[number];

export const CASE_STATUS_LABELS: Record<CaseStatus, string> = {
  DETECTED: "Обнаружен",
  UNDER_REVIEW: "На проверке",
  CONFIRMED_FAKE: "Подделка подтверждена",
  FALSE_POSITIVE: "Ложное срабатывание",
  COMPLAINT_FILED: "Жалоба подана",
  LISTING_REMOVED: "Карточка удалена",
  CLOSED: "Закрыт",
};

export const CASE_STATUS_COLORS: Record<CaseStatus, string> = {
  DETECTED: "#ff9f0a",
  UNDER_REVIEW: "#007aff",
  CONFIRMED_FAKE: "#ff2d55",
  FALSE_POSITIVE: "#8e8e93",
  COMPLAINT_FILED: "#af52de",
  LISTING_REMOVED: "#34c759",
  CLOSED: "#8e8e93",
};
