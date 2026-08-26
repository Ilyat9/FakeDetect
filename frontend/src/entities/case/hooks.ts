import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  addCaseComment,
  bulkTransition,
  fetchCaseDetail,
  fetchCases,
  fetchComments,
  fetchRevenue,
  fetchTimeseries,
  fetchTiming,
  fetchTopSellers,
  transitionCase,
} from "./api";
import type { CaseStatus } from "@/shared/config";
import { toast } from "sonner";

export function useCasesQuery(status: CaseStatus | "all") {
  return useQuery({
    queryKey: ["cases", "list", status],
    queryFn: ({ signal }) => fetchCases(status, signal),
    staleTime: 15_000,
  });
}

export function useCaseDetailQuery(id: number) {
  return useQuery({
    queryKey: ["cases", "detail", id],
    queryFn: ({ signal }) => fetchCaseDetail(id, signal),
    // Comments/timeline freshness matters while the case is being worked on.
    refetchInterval: 15_000,
  });
}

export function useTransitionMutation(caseId?: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { to_status: CaseStatus; comment?: string }) =>
      transitionCase(caseId ?? -1, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["cases"] });
      toast.success("Статус кейса обновлён");
    },
    onError: (e) => toast.error(`Не удалось сменить статус: ${e.message}`),
  });
}

export function useBulkTransitionMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ ids, to }: { ids: number[]; to: CaseStatus }) => bulkTransition(ids, to),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["cases"] });
      toast.success("Массовый переход выполнен");
    },
    onError: (e) => toast.error(`Массовый переход не удался: ${e.message}`),
  });
}

export function useAddCommentMutation(caseId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (text: string) => addCaseComment(caseId, text),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["cases", "comments", caseId] });
      void qc.invalidateQueries({ queryKey: ["cases", "detail", caseId] });
    },
    onError: (e) => toast.error(`Комментарий не сохранён: ${e.message}`),
  });
}

export function useCommentsQuery(caseId: number) {
  return useQuery({
    queryKey: ["cases", "comments", caseId],
    queryFn: ({ signal }) => fetchComments(caseId, signal),
    refetchInterval: 15_000,
  });
}

// --- analytics --------------------------------------------------------------

export function useTimeseriesQuery(enabled = true) {
  return useQuery({
    queryKey: ["analytics", "timeseries"],
    queryFn: ({ signal }) => fetchTimeseries(signal),
    staleTime: 120_000,
    retry: 1,
    enabled,
  });
}

export function useTopSellersQuery(enabled = true) {
  return useQuery({
    queryKey: ["analytics", "top-sellers"],
    queryFn: ({ signal }) => fetchTopSellers(signal),
    staleTime: 120_000,
    retry: 1,
    enabled,
  });
}

export function useRevenueQuery(enabled = true) {
  return useQuery({
    queryKey: ["analytics", "revenue"],
    queryFn: ({ signal }) => fetchRevenue(signal),
    staleTime: 300_000,
    retry: 1,
    enabled,
  });
}

export function useTimingQuery(enabled = true) {
  return useQuery({
    queryKey: ["analytics", "timing"],
    queryFn: ({ signal }) => fetchTiming(signal),
    staleTime: 300_000,
    retry: 1,
    enabled,
  });
}
