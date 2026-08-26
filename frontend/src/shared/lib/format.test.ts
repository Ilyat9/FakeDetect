import { describe, expect, it } from "vitest";

import {
  formatCurrency,
  formatDate,
  formatDuration,
  SCHEDULE_PRESETS,
} from "./format";

describe("format utils", () => {
  it("formats dates in ru locale and dashes for null", () => {
    expect(formatDate("2026-08-26T10:00:00Z")).toMatch(/\d{2}\.\d{2}\.2026/);
    expect(formatDate(null)).toBe("—");
  });

  it("formats currency without kopecks", () => {
    expect(formatCurrency(123_450)).toContain("123");
  });

  it("formats durations humanly", () => {
    expect(formatDuration(90 * 60_000)).toBe("1 ч");
    expect(formatDuration(30 * 1000)).toBe("< 1 мин");
  });

  it("maps frequency presets to cron so users never write cron by hand", () => {
    expect(SCHEDULE_PRESETS.daily).toBe("0 7 * * *");
    expect(SCHEDULE_PRESETS.weekly).toBe("0 7 * * 1");
  });
});
