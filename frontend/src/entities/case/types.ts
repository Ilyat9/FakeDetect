import type { CaseStatus } from "@/shared/config";

/** Analytics endpoints (Block E) — routers/analytics.py. */
export interface TimeSeriesPoint {
  date: string;
  total: number;
  fakes: number;
}

export interface TopSeller {
  seller: string;
  marketplace: string | null;
  checks: number;
  fakes: number;
}

/** GET /analytics/revenue — app.database.get_protected_revenue() response shape. */
export interface RevenueProtected {
  confirmed_fakes: number;
  avg_original_price: number | null;
  protected_revenue_estimate: number | null;
  disclaimer: string;
}

export interface TimingMetrics {
  avg_time_to_detection_hours: number;
  avg_time_to_resolution_hours: number;
}

export interface CaseRow {
  id: number;
  check_id: number;
  url: string | null;
  brand: string | null;
  marketplace: string | null;
  seller: string | null;
  verdict: string | null;
  status: CaseStatus;
  assignee: string | null;
  sla_deadline: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface CaseDetail {
  case: CaseRow;
  history: CaseHistoryEntry[];
  comments: CaseComment[];
}

export interface CaseHistoryEntry {
  id: number;
  from_status: string | null;
  to_status: string;
  changed_by: string | null;
  comment: string | null;
  created_at: string | null;
}

export interface CaseComment {
  id: number;
  author: string;
  text: string;
  created_at: string | null;
}
