import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { batchRefetchInterval, useBatchTaskQuery } from "./hooks";
import type { BatchTask } from "./api";
import { server } from "@/test/mocks/server";

/**
 * REGRESSION GUARD for spec 3.4.
 *
 * In v1 the frontend polled until "done" while the backend reports
 * "completed" — polling never stopped and the whole batch flow broke.
 * These tests pin the contract: only `completed` and `error` stop polling;
 * anything else keeps the 3s interval armed.
 */

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

function task(status: string): BatchTask {
  return { id: "t", total: 4, done: 2, status };
}

describe("batchRefetchInterval — backend status contract", () => {
  it.each(["completed", "error"])("stops polling on final status '%s'", (status) => {
    expect(batchRefetchInterval({ state: { data: task(status) } })).toBe(false);
  });

  it("keeps polling while 'processing'", () => {
    expect(batchRefetchInterval({ state: { data: task("processing") } })).toBe(3_000);
  });

  it("treats legacy 'done' as NON-final so a contract drift cannot silently pass", () => {
    expect(batchRefetchInterval({ state: { data: task("done") } })).toBe(3_000);
  });

  it("keeps polling when no data yet", () => {
    expect(batchRefetchInterval({ state: {} })).toBe(3_000);
  });
});

describe("useBatchTaskQuery against MSW mocks of the real response shape", () => {
  it("delivers a completed task without error", async () => {
    server.use(
      http.get("*/api/v1/batch/:taskId", () =>
        HttpResponse.json({ id: "t1", total: 2, done: 2, status: "completed", error: null }),
      ),
    );
    const { result } = renderHook(() => useBatchTaskQuery("t1"), { wrapper: createWrapper() });
    await waitFor(() => { expect(result.current.data?.status).toBe("completed"); });
    expect(result.current.data?.done).toBe(2);
  });

  it("surfaces the backend error payload for failed tasks", async () => {
    server.use(
      http.get("*/api/v1/batch/:taskId", () =>
        HttpResponse.json({ id: "t2", total: 5, done: 0, status: "error", error: "LLM down" }),
      ),
    );
    const { result } = renderHook(() => useBatchTaskQuery("t2"), { wrapper: createWrapper() });
    await waitFor(() => { expect(result.current.data?.status).toBe("error"); });
    expect(result.current.data?.error).toBe("LLM down");
  });
});
