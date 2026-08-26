import { apiFetch } from "@/shared/api/client";

/**
 * Batch task status contract — REGRESSION GUARD.
 *
 * The backend reports exactly: processing -> completed | error
 * (routers/batch.py: `status: task["status"]  # processing | completed | error`).
 * In v1 a mismatch ("done" vs "completed") broke the whole batch UI: polling
 * never stopped. isBatchFinalStatus() must stay in sync — covered by
 * src/entities/batch/api.test.ts against MSW mocks of the real response shape.
 */
export interface BatchTask {
  id: string;
  total: number;
  done: number;
  status: string;
  error?: string | null;
}

export function fetchBatchTask(taskId: string, signal?: AbortSignal): Promise<BatchTask> {
  return apiFetch<BatchTask>(`/batch/${taskId}`, { signal });
}

export async function startBatch(
  file: File,
  referenceImage: File | null,
  provider: string,
): Promise<{ task_id: string }> {
  const formData = new FormData();
  formData.set("file", file);
  formData.set("provider", provider);
  if (referenceImage) formData.set("reference", referenceImage);
  return apiFetch("/batch", { method: "POST", formData, timeoutMs: 60_000 });
}

export function buildBatchDownloadUrl(taskId: string): string {
  return `${import.meta.env.VITE_API_URL ?? "/api/v1"}/batch/${taskId}/download`;
}
