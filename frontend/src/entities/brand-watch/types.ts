/** Row of brand_watches table (reference images are stripped server-side). */
export interface BrandWatch {
  id: number;
  brand_name: string;
  keywords: string;
  marketplaces: string;
  cron_schedule: string;
  digest_interval_hours: number;
  is_active: number;
  last_run_at: string | null;
  next_run_at: string | null;
  last_status: string | null;
  created_at: string | null;
  tenant_id?: number;
}

export interface WatchListing {
  id: number;
  watch_id: number;
  url: string;
  sku: string | null;
  title: string | null;
  price: number | null;
  seller: string | null;
  thumbnail_url: string | null;
  /** new | analyzed | skipped_duplicate | error */
  status: string;
  verdict: string | null;
  discovered_at: string | null;
}
