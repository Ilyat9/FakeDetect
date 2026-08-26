import { API_URL } from "@/shared/config";
import { ApiError } from "./errors";

/**
 * Credential provider abstraction: the auth layer registers how to obtain the
 * current X-API-Key (the backend's auth model — see services/tenancy.py).
 * The client itself never touches storage directly.
 */
export type CredentialsProvider = () => string | undefined;
export type OnUnauthorized = () => void;

let getCredentials: CredentialsProvider = () => undefined;
let onUnauthorized: OnUnauthorized = () => undefined;

export function registerCredentials(provider: CredentialsProvider): void {
  getCredentials = provider;
}

export function registerUnauthorizedHandler(handler: OnUnauthorized): void {
  onUnauthorized = handler;
}

const DEFAULT_TIMEOUT_MS = 30_000;

export interface RequestOptions {
  method?: "GET" | "POST" | "DELETE";
  query?: Record<string, string | number | boolean | undefined>;
  body?: unknown;
  formData?: FormData;
  signal?: AbortSignal;
  timeoutMs?: number;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  // Relative URLs are intentional: the SPA and API share one origin in every
  // environment (dev proxy / nginx). Avoids dependence on window.location
  // quirks in non-browser runtimes.
  const qs = new URLSearchParams();
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== "") {
        qs.set(key, String(value));
      }
    }
  }
  const search = qs.toString();
  return `${API_URL}${path}${search ? `?${search}` : ""}`;
}

/**
 * Single fetch wrapper: attaches X-API-Key, enforces timeouts, normalizes
 * errors into typed ApiError (with backend request_id) and routes 401/403
 * to the registered unauthorized handler.
 */
/**
 * Some runtimes (vitest jsdom + Node/undici fetch) mix AbortController
 * implementations: fetch rejects a foreign signal instance outright.
 * In that case retry once without the custom signal — the timeout is lost,
 * but the request itself (and MSW interception) keeps working. Browsers are
 * unaffected and keep full timeout support.
 */
async function fetchWithSignalFallback(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (e) {
    if (
      init.signal &&
      e instanceof TypeError &&
      /AbortSignal/i.test(e.message)
    ) {
      const { signal: _ignored, ...rest } = init;
      void _ignored;
      return fetch(url, rest);
    }
    throw e;
  }
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", query, body, formData, signal, timeoutMs = DEFAULT_TIMEOUT_MS } =
    options;

  const controller = new AbortController();
  const abortFromTimeout = setTimeout(() => { controller.abort(); }, timeoutMs);
  if (signal) {
    signal.addEventListener("abort", () => { controller.abort(); }, { once: true });
  }

  const headers: Record<string, string> = {};
  const apiKey = getCredentials();
  if (apiKey) {
    headers["X-API-Key"] = apiKey;
  }
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  try {
    const response = await fetchWithSignalFallback(
      buildUrl(path, query),
      {
        method,
        headers,
        body: formData ?? (body !== undefined ? JSON.stringify(body) : undefined),
        signal: controller.signal,
      },
    );

    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try {
        const payload: unknown = await response.json();
        if (
          payload &&
          typeof payload === "object" &&
          "detail" in payload &&
          typeof (payload).detail === "string"
        ) {
          detail = (payload as { detail: string }).detail;
        }
      } catch {
        /* non-JSON error body — keep default detail */
      }
      if (response.status === 401 || response.status === 403) {
        onUnauthorized();
      }
      throw new ApiError(
        response.status,
        detail,
        response.headers.get("X-Request-ID") ?? undefined,
      );
    }

    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  } catch (e) {
    if (e instanceof ApiError) {
      throw e;
    }
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new ApiError(0, "Превышено время ожидания запроса или запрос отменён");
    }
    throw new ApiError(0, "Сеть недоступна. Проверьте подключение и повторите.");
  } finally {
    clearTimeout(abortFromTimeout);
  }
}
