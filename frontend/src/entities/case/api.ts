import { apiFetch } from "@/shared/api/client";
import type { CaseStatus } from "@/shared/config";
import type {
  CaseComment,
  CaseDetail,
  CaseRow,
  TimeSeriesPoint,
  TimingMetrics,
  TopSeller,
  RevenueProtected,
} from "./types";

export const caseKeys = {
  all: ["cases"] as const,
  list: (status: CaseStatus | "all") => [...caseKeys.all, "list", status] as const,
  detail: (id: number) => [...caseKeys.all, "detail", id] as const,
  comments: (id: number) => [...caseKeys.all, "comments", id] as const,
};

export function fetchCases(status: CaseStatus | "all", signal?: AbortSignal) {
  return apiFetch<{ cases: CaseRow[]; total: number }>("/cases", {
    query: { status: status === "all" ? undefined : status },
    signal,
  });
}

export function fetchCaseDetail(id: number, signal?: AbortSignal): Promise<CaseDetail> {
  return apiFetch<CaseDetail>(`/cases/${id}`, { signal });
}

export interface TransitionPayload {
  to_status: CaseStatus;
  comment?: string;
}

export async function transitionCase(
  caseId: number,
  payload: TransitionPayload,
): Promise<{ status: string }> {
  return apiFetch(`/cases/${caseId}/transition`, {
    method: "POST",
    body: { to_status: payload.to_status, comment: payload.comment ?? "", changed_by: "web-ui" },
  });
}

export async function bulkTransition(
  caseIds: number[],
  to_status: CaseStatus,
): Promise<{ results: unknown }> {
  return apiFetch("/cases/bulk-transition", {
    method: "POST",
    body: { case_ids: caseIds, to_status, changed_by: "web-ui", comment: "" },
  });
}

export async function addCaseComment(caseId: number, text: string): Promise<void> {
  await apiFetch(`/cases/${caseId}/comments`, {
    method: "POST",
    body: { author: "web-ui", text },
  });
}

export function fetchComments(caseId: number, signal?: AbortSignal) {
  return apiFetch<{ comments: CaseComment[] }>(`/cases/${caseId}/comments`, { signal });
}

/** Downloads the evidence PDF; returns raw bytes for a client-side save. */
export async function downloadEvidencePdf(caseId: number): Promise<Blob> {
  const response = await fetch(`${import.meta.env.VITE_API_URL ?? "/api/v1"}/cases/${caseId}/evidence-pdf`);
  if (!response.ok) throw new Error(`Не удалось скачать evidence-PDF (HTTP ${response.status})`);
  return response.blob();
}

export function fetchComplaintText(caseId: number): Promise<{ marketplace: string; text: string; note?: string }> {
  return apiFetch(`/cases/${caseId}/complaint`);
}

// --- analytics (Block E endpoints) ------------------------------------------

export const analyticsKeys = {
  all: ["analytics"] as const,
  timeseries: () => [...analyticsKeys.all, "timeseries"] as const,
  topSellers: () => [...analyticsKeys.all, "top-sellers"] as const,
  revenue: () => [...analyticsKeys.all, "revenue"] as const,
  timing: () => [...analyticsKeys.all, "timing"] as const,
};

function unwrap<T>(key: string, signal?: AbortSignal): Promise<T> {
  return apiFetch<T>(key, { signal });
}

export const fetchTimeseries = (signal?: AbortSignal) =>
  apiFetch<{ points: TimeSeriesPoint[] }>("/analytics/timeseries", { signal });

export const fetchTopSellers = (signal?: AbortSignal) =>
  apiFetch<{ sellers: TopSeller[] }>("/analytics/top-sellers", { signal });

export const fetchRevenue = (signal?: AbortSignal) =>
  apiFetch<RevenueProtected>("/analytics/revenue", { signal });

export const fetchTiming = (signal?: AbortSignal) =>
  unwrap<TimingMetrics>("/analytics/timing", signal);
