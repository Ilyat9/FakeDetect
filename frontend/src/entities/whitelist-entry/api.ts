import { apiFetch } from "@/shared/api/client";
import type { WhitelistEntry } from "./types";

export const whitelistKeys = {
  all: ["whitelist"] as const,
};

export function fetchWhitelist(signal?: AbortSignal) {
  return apiFetch<{ entries: WhitelistEntry[]; total: number }>("/whitelist", { signal });
}

export interface AddWhitelistPayload {
  brand: string;
  sellerName: string;
  marketplace?: string;
  note?: string;
}

/**
 * POST /whitelist is an ADMIN operation with real consequences: whitelisted
 * sellers automatically receive the «оригинал» verdict. The UI must always
 * confirm this action in a modal before calling.
 */
export async function addToWhitelist(payload: AddWhitelistPayload): Promise<void> {
  const formData = new FormData();
  formData.set("brand", payload.brand);
  formData.set("seller_name", payload.sellerName);
  if (payload.marketplace) formData.set("marketplace", payload.marketplace);
  if (payload.note) formData.set("note", payload.note);
  await apiFetch("/whitelist", { method: "POST", formData });
}

export async function removeFromWhitelist(entryId: number): Promise<void> {
  await apiFetch(`/whitelist/${entryId}`, { method: "DELETE" });
}
