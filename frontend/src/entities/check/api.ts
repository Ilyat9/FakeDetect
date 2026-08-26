import { apiFetch } from "@/shared/api/client";
import type {
  HistoryFilters,
  HistoryPage,
  StatsOverview,
} from "./types";

export const checkKeys = {
  all: ["checks"] as const,
  history: (filters: HistoryFilters) => [...checkKeys.all, "history", filters] as const,
  stats: () => [...checkKeys.all, "stats"] as const,
};

export function fetchHistory(filters: HistoryFilters, signal?: AbortSignal): Promise<HistoryPage> {
  return apiFetch<HistoryPage>("/history", {
    query: {
      limit: filters.limit,
      offset: filters.offset,
      brand: filters.brand || undefined,
    },
    signal,
  });
}

export function fetchStats(signal?: AbortSignal): Promise<StatsOverview> {
  return apiFetch<StatsOverview>("/stats", { signal });
}

/** Result of POST /analyze and /analyze-deep (routers/analysis.py). */
export interface AnalysisResult {
  verdict?: string;
  confidence?: number;
  risk_level?: string;
  summary?: string;
  price_original?: number;
  price_suspect?: number;
  provider?: string;
  request_id?: string;
  [key: string]: unknown;
}

export interface AnalyzePayload {
  mode: "files" | "url";
  reference?: File | null;
  suspect?: File | null;
  url?: string;
  deep: boolean;
  provider: string;
}

/**
 * POST /analyze | /analyze-deep — multipart with images or a marketplace URL.
 * Returns the parsed analysis result; errors are normalized ApiErrors.
 */
export async function analyze(payload: AnalyzePayload, signal?: AbortSignal): Promise<AnalysisResult> {
  const formData = new FormData();
  const endpoint = payload.deep ? "/analyze-deep" : "/analyze";
  if (payload.mode === "url") {
    if (!payload.url) throw new Error("URL обязателен для режима URL");
    formData.set("image_url", payload.url);
  } else {
    if (payload.reference) formData.set("reference", payload.reference);
    if (payload.suspect) formData.set("suspect", payload.suspect);
  }
  formData.set("provider", payload.provider);
  return apiFetch<AnalysisResult>(endpoint, { method: "POST", formData, timeoutMs: 120_000, signal });
}
