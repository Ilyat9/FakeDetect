import { describe, expect, it } from "vitest";

import { whitelistEntrySchema } from "@/pages/whitelist/whitelist-page";
import { createWatchSchema } from "@/pages/brand-watches/brand-watches-page";

describe("whitelistEntrySchema", () => {
  it("accepts a valid entry", () => {
    const parsed = whitelistEntrySchema.safeParse({
      brand: "Acme",
      sellerName: "Official Store",
      marketplace: "WB",
      note: "",
    });
    expect(parsed.success).toBe(true);
  });

  it("rejects empty brand/seller with messages", () => {
    const parsed = whitelistEntrySchema.safeParse({ brand: "", sellerName: "", marketplace: "", note: "" });
    expect(parsed.success).toBe(false);
    if (!parsed.success) {
      expect(parsed.error.issues.map((i) => i.message)).toContain("Укажите бренд");
    }
  });
});

describe("createWatchSchema", () => {
  it("requires at least one marketplace", () => {
    const parsed = createWatchSchema.safeParse({ brandName: "B", keywords: "k", marketplaces: [] });
    expect(parsed.success).toBe(false);
  });

  it("requires at least one keyword", () => {
    const parsed = createWatchSchema.safeParse({ brandName: "B", keywords: "", marketplaces: ["WB"] });
    expect(parsed.success).toBe(false);
  });
});

/* Re-export guard: importing pages must not execute side effects at module load. */
describe("page modules import cleanly", () => {
  it("schemas are exported values", () => {
    expect(typeof whitelistEntrySchema.safeParse).toBe("function");
    expect(typeof createWatchSchema.safeParse).toBe("function");
  });
});
