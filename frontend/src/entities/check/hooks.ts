import { useMutation, useQuery } from "@tanstack/react-query";

import {
  analyze,
  fetchHistory,
  fetchStats,
  type AnalysisResult,
  type AnalyzePayload,
} from "./api";
import type { HistoryFilters } from "./types";

/** Dashboard counters — cheap and stable; cache for a minute. */
export function useStatsQuery() {
  return useQuery({
    queryKey: ["checks", "stats"],
    queryFn: ({ signal }) => fetchStats(signal),
    staleTime: 60_000,
  });
}

/**
 * Server-side pagination from day one: the page state IS the query key.
 * No client-side slicing — the backend supports limit/offset natively.
 */
export function useHistoryQuery(filters: HistoryFilters) {
  return useQuery({
    queryKey: ["checks", "history", filters],
    queryFn: ({ signal }) => fetchHistory(filters, signal),
    placeholderData: (prev) => prev,
  });
}

export function useAnalyzeMutation() {
  return useMutation<AnalysisResult, Error, AnalyzePayload>({
    mutationFn: (payload) => analyze(payload),
  });
}
