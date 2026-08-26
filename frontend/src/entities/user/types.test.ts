import { describe, expect, it } from "vitest";

import { roleSatisfies, type Role } from "./types";

describe("role model (mirrors services/tenancy.py)", () => {
  const matrix: [Role, "viewer" | "analyst" | "admin" | "owner", boolean][] = [
    ["owner", "admin", true],
    ["owner", "viewer", true],
    ["admin", "admin", true],
    ["analyst", "admin", false],
    ["viewer", "admin", false],
    ["viewer", "viewer", true],
  ];

  it.each(matrix)("role %s satisfies min %s: %p", (role, min, expected) => {
    expect(roleSatisfies(role, min)).toBe(expected);
  });

  it("legal never satisfies numeric role floors", () => {
    expect(roleSatisfies("legal", "viewer")).toBe(false);
  });
});
