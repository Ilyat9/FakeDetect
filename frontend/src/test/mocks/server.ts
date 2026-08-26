import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

/**
 * MSW mocks mirror REAL backend response shapes (routers/*.py).
 * The batch handler below is the regression guard for spec 3.4.
 */
export const handlers = [
  http.get("*/api/v1/batch/:taskId", ({ params }) =>
    HttpResponse.json({
      id: params.taskId,
      total: 3,
      done: 1,
      status: "processing",
      error: null,
    }),
  ),
  http.get("*/api/v1/stats", () =>
    HttpResponse.json({ total: 10, fakes: 4, originals: 5, suspicious: 1 }),
  ),
];

export const server = setupServer(...handlers);
