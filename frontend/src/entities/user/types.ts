export type Role = "owner" | "admin" | "analyst" | "viewer" | "legal";

const ROLE_RANK: Record<Exclude<Role, "legal">, number> = {
  owner: 4,
  admin: 3,
  analyst: 2,
  viewer: 1,
};

/** Mirrors services/tenancy.py require_ctx semantics. */
export function roleSatisfies(role: Role, minRole: Exclude<Role, "legal">): boolean {
  if (role === "legal") return false;
  return ROLE_RANK[role] >= ROLE_RANK[minRole];
}

export interface Session {
  apiKey: string;
  role: Role;
  tenantId: number | null;
}
