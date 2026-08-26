import { apiFetch } from "@/shared/api/client";
import type { Marketplace } from "@/shared/config";
import type { ScheduleFrequency } from "@/shared/lib/format";
import { SCHEDULE_PRESETS } from "@/shared/lib/format";
import type { BrandWatch, WatchListing } from "./types";

export const watchKeys = {
  all: ["watches"] as const,
  list: (activeOnly: boolean) => [...watchKeys.all, "list", activeOnly] as const,
  listings: (id: number) => [...watchKeys.all, "listings", id] as const,
};

export function fetchWatches(activeOnly = false, signal?: AbortSignal) {
  return apiFetch<{ watches: BrandWatch[]; total: number }>("/watches", {
    query: { active_only: activeOnly },
    signal,
  });
}

export function fetchWatchListings(watchId: number, signal?: AbortSignal) {
  return apiFetch<{ listings: WatchListing[]; total: number }>(
    `/watches/${watchId}/listings`,
    { query: { limit: 100 }, signal },
  );
}

export interface CreateWatchPayload {
  brandName: string;
  keywords: string[];
  marketplaces: Marketplace[];
  frequency: ScheduleFrequency;
  reference: File;
}

/** POST /watches — multipart; the UI maps a simple frequency preset to cron. */
export async function createWatch(payload: CreateWatchPayload): Promise<{ id: number }> {
  const formData = new FormData();
  formData.set("brand_name", payload.brandName);
  formData.set("keywords", payload.keywords.join(","));
  formData.set("marketplaces", payload.marketplaces.join(","));
  formData.set("cron_schedule", SCHEDULE_PRESETS[payload.frequency]);
  formData.set("digest_interval_hours", "24");
  formData.set("reference", payload.reference);
  return apiFetch("/watches", {
    method: "POST",
    formData,
    timeoutMs: 60_000,
  });
}

export async function deleteWatch(watchId: number): Promise<void> {
  await apiFetch(`/watches/${watchId}`, { method: "DELETE" });
}

export async function runWatchNow(watchId: number): Promise<void> {
  await apiFetch(`/watches/${watchId}/run-now`, { method: "POST" });
}
