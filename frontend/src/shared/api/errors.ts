/** Typed API error carrying backend-provided request_id for support correlation. */
export class ApiError extends Error {
  readonly status: number;
  /** Backend X-Request-ID / body request_id — quote it to support when debugging. */
  readonly requestId?: string;
  readonly code?: string;

  constructor(status: number, message: string, requestId?: string, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.requestId = requestId;
    this.code = code ?? httpErrorCode(status);
  }
}

export function httpErrorCode(status: number): string | undefined {
  switch (status) {
    case 400:
      return "BAD_REQUEST";
    case 401:
      return "UNAUTHORIZED";
    case 403:
      return "FORBIDDEN";
    case 404:
      return "NOT_FOUND";
    case 429:
      return "RATE_LIMITED";
    default:
      return status >= 500 ? "SERVER_ERROR" : undefined;
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}
