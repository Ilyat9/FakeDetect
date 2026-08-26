import { create } from "zustand";

import type { Session } from "../types";

/**
 * Auth session store.
 *
 * SECURITY NOTE (deliberate compromise, see frontend README):
 * the backend authenticates via X-API-Key (services/tenancy.py) — there is no
 * cookie/JWT flow to delegate storage to. The key is therefore held IN MEMORY
 * by default. A sessionStorage mirror exists purely to survive dev-server HMR
 * reloads; it is cleared on logout and never persisted to localStorage.
 * For production hardening prefer a reverse-proxy that injects the key
 * server-side after an SSO login, keeping it out of JS entirely.
 */
interface AuthState {
  session: Session | null;
  setSession: (session: Session) => void;
  clearSession: () => void;
}

const STORAGE_KEY = "fakedetect-session-hmr";

function loadHmrMirror(): Session | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

export const useAuthStore = create<AuthState>((set) => ({
  session: loadHmrMirror(),
  setSession: (session) => {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
    } catch {
      /* storage unavailable — memory-only is fine */
    }
    set({ session });
  },
  clearSession: () => {
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
    set({ session: null });
  },
}));

export function getSession(): Session | null {
  return useAuthStore.getState().session;
}
