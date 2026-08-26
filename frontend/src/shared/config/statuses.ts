import type { CaseStatus } from "@/shared/config";

/** Verdicts as returned by the backend aggregator (see aggregator.py / parsers). */
export const VERDICTS = ["ПОДДЕЛКА", "ОРИГИНАЛ", "ТРЕБУЕТ РУЧНОЙ ПРОВЕРКИ"] as const;
export type Verdict = (typeof VERDICTS)[number];

export function isFakeVerdict(v: string): boolean {
  return v.toUpperCase().includes("ПОДДЕЛКА");
}

export function isOriginalVerdict(v: string): boolean {
  return v.toUpperCase().includes("ОРИГИНАЛ");
}

/** Final batch task statuses — MUST match routers/batch.py exactly. */
export const BATCH_FINAL_STATUSES = ["completed", "error"] as const;
export const BATCH_ACTIVE_STATUSES = ["processing"] as const;

export function isBatchFinalStatus(status: string): boolean {
  return (BATCH_FINAL_STATUSES as readonly string[]).includes(status);
}

/**
 * Valid case status transitions (mirrors the state machine enforced by
 * database.py transition_case). Used for UI hints; server remains the source
 * of truth and will reject invalid transitions regardless.
 */
export const CASE_TRANSITIONS: Record<CaseStatus, readonly CaseStatus[]> = {
  DETECTED: ["UNDER_REVIEW", "FALSE_POSITIVE"],
  UNDER_REVIEW: ["CONFIRMED_FAKE", "FALSE_POSITIVE"],
  CONFIRMED_FAKE: ["COMPLAINT_FILED", "CLOSED"],
  FALSE_POSITIVE: ["CLOSED"],
  COMPLAINT_FILED: ["LISTING_REMOVED", "CLOSED"],
  LISTING_REMOVED: ["CLOSED"],
  CLOSED: [],
};
