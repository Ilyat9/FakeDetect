import { useQuery } from "@tanstack/react-query";

import { fetchBatchTask, type BatchTask } from "./api";
import { isBatchFinalStatus } from "@/shared/config/statuses";

const POLL_INTERVAL_MS = 3_000;

/** Query-state shape needed by the interval resolver. */
interface IntervalQuery {
  state: { data?: BatchTask | null };
}

/**
 * Pure polling-interval resolver so the stop-condition contract is directly
 * unit-testable without rendering the hook.
 */
export function batchRefetchInterval(query: IntervalQuery): number | false {
  const status = query.state.data?.status;
  return status && isBatchFinalStatus(status) ? false : POLL_INTERVAL_MS;
}

/**
 * Polls a batch task until a FINAL backend status is reached.
 *
 * The stop condition uses the shared isBatchFinalStatus() guard whose values
 * ("completed" | "error") MUST match routers/batch.py exactly — a regression
 * here (e.g. "done") previously broke the whole batch flow. Locked by
 * hooks.test.tsx (MSW contract tests).
 */
export function useBatchTaskQuery(taskId: string | null) {
  return useQuery<BatchTask>({
    queryKey: ["batch", taskId],
    queryFn: ({ signal }) => fetchBatchTask(taskId as string, signal),
    enabled: taskId !== null,
    refetchInterval: batchRefetchInterval,
    // Batch runs are long; don't spam retries on transient network blips
    // because polling itself provides resilience.
    retry: 1,
    staleTime: 0,
  });
}
