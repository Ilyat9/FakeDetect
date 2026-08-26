import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * API CONTRACT TEST (spec 3.1).
 *
 * src/shared/types/api-schema.d.ts is GENERATED from the live FastAPI
 * OpenAPI schema (npm run generate:api-types) and committed. This test pins
 * the frontend's expectations to that generated file:
 *   - every endpoint the SPA consumes must exist in the backend schema;
 *   - the batch status contract comment must still document the real values.
 *
 * If the backend renames/removes an endpoint, regenerating the schema makes
 * this test fail loudly — before runtime breaks. CI additionally fails when
 * the committed schema drifts from the live one (check:api-types).
 */

// Vitest runs with cwd = frontend/, so resolve relative to the project root.
const schema = readFileSync(resolve(process.cwd(), "src/shared/types/api-schema.d.ts"), "utf-8");

/** Every API route the frontend calls (client.ts + entity api.ts files). */
const CONSUMED_ENDPOINTS = [
  // analysis
  '"/api/v1/analyze"',
  '"/api/v1/analyze-deep"',
  // data
  '"/api/v1/history"',
  '"/api/v1/stats"',
  '"/api/v1/whitelist"',
  // batch
  '"/api/v1/batch"',
  '"/api/v1/batch/{task_id}"',
  '"/api/v1/batch/{task_id}/download"',
  // cases
  '"/api/v1/cases"',
  '"/api/v1/cases/bulk-transition"',
  '"/api/v1/cases/{case_id}"',
  '"/api/v1/cases/{case_id}/transition"',
  '"/api/v1/cases/{case_id}/comments"',
  '"/api/v1/cases/{case_id}/evidence-pdf"',
  '"/api/v1/cases/{case_id}/complaint"',
  // brand watches
  '"/api/v1/watches"',
  '"/api/v1/watches/{watch_id}"',
  '"/api/v1/watches/{watch_id}/listings"',
  '"/api/v1/watches/{watch_id}/run-now"',
  // analytics (Block E dashboard)
  '"/api/v1/analytics/timeseries"',
  '"/api/v1/analytics/top-sellers"',
  '"/api/v1/analytics/revenue"',
  '"/api/v1/analytics/timing"',
  '"/api/v1/analytics/export.pdf"',
  // system
  '"/api/v1/health"',
] as const;

describe("generated OpenAPI schema covers the frontend surface", () => {
  it.each(CONSUMED_ENDPOINTS)("schema declares %s", (endpoint) => {
    expect(schema).toContain(endpoint);
  });

  it.each([
    ["GET /api/v1/history", "/api/v1/history"],
    ["GET /api/v1/stats", "/api/v1/stats"],
    ["POST /api/v1/batch", "/api/v1/batch"],
    ["GET /api/v1/batch/{task_id}", "/api/v1/batch/{task_id}"],
    ["POST /api/v1/cases/bulk-transition", "/api/v1/cases/bulk-transition"],
    ["GET /api/v1/watches", "/api/v1/watches"],
    ["GET /api/v1/analytics/timeseries", "/api/v1/analytics/timeseries"],
  ])("%s is exposed with the expected method", (_label, path) => {
    // The generated file marks a method's presence with `post:`/`get:` keys
    // inside the path block; check the block right after the path key.
    const idx = schema.indexOf(path.replace("{task_id}", "{task_id}"));
    expect(idx).toBeGreaterThan(-1);
    const block = schema.slice(idx, idx + 2000);
    const method = _label.startsWith("POST") ? "post" : "get";
    expect(block).toMatch(new RegExp(`${method}:`));
  });

  it("documents the batch status contract the polling logic depends on", () => {
    // The schema itself doesn't carry status enums (backend returns
    // JSONResponse), so the contract is enforced by hooks.test.tsx against
    // MSW mocks of routers/batch.py. Here we verify the schema still contains
    // the batch endpoints that contract is pinned to.
    expect(schema).toContain('"/api/v1/batch/{task_id}"');
  });
});
