/** Row of the backend `checks` table as returned by GET /history. */
export interface Check {
  id: number;
  url: string | null;
  brand: string | null;
  marketplace: string | null;
  verdict: string | null;
  confidence: number | null;
  risk_level: string | null;
  summary: string | null;
  price_original: number | null;
  price_suspect: number | null;
  result_icon: string | null;
  checked_at: string | null;
  seller: string | null;
}

export interface HistoryPage {
  checks: Check[];
  total: number;
  limit: number;
  offset: number;
}

export interface HistoryFilters {
  brand?: string;
  limit: number;
  offset: number;
}

/** GET /stats response. */
export interface StatsOverview {
  total: number;
  fakes: number;
  originals: number;
  suspicious: number;
}

export interface HistoryQueryResult {
  page: HistoryPage;
  filters: HistoryFilters;
}
