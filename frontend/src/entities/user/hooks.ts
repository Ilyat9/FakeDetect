import { useEffect } from "react";

import { registerCredentials, registerUnauthorizedHandler } from "@/shared/api/client";
import { useAuthStore } from "./model/auth-store";
import type { Role } from "./types";

export interface UseAuthResult {
  apiKey: string | null;
  role: Role | null;
  tenantId: number | null;
  isAuthenticated: boolean;
  login: (apiKey: string) => void;
  logout: () => void;
}

/**
 * AuthProvider wiring between the session store and the API client:
 * - every outgoing request gets X-API-Key from the store;
 * - any 401/403 clears the session (single source of truth).
 * Role/tenant are derived from the login response probe (see LoginPage).
 */
export function useAuth(): UseAuthResult {
  const session = useAuthStore((s) => s.session);
  const setSession = useAuthStore((s) => s.setSession);
  const clearSession = useAuthStore((s) => s.clearSession);

  useEffect(() => {
    registerCredentials(() => useAuthStore.getState().session?.apiKey);
    registerUnauthorizedHandler(() => { useAuthStore.getState().clearSession(); });
  }, []);

  return {
    apiKey: session?.apiKey ?? null,
    role: session?.role ?? null,
    tenantId: session?.tenantId ?? null,
    isAuthenticated: session !== null,
    login: (apiKey: string) => { setSession({ apiKey, role: "owner", tenantId: null }); },
    logout: clearSession,
  };
}
