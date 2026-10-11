/**
 * The API error type. Mirrors the backend's single error envelope so screens can
 * branch on a stable machine code rather than parsing messages.
 */

/** The backend's single error envelope. */
export interface ApiErrorEnvelope {
  error: ApiErrorBody;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  request_id?: string | null;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly requestId: string | null;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
    requestId: string | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }

  /** True when the request never reached the server. */
  get isNetworkError(): boolean {
    return this.status === 0;
  }

  /** True when signing in again is the fix. */
  get isAuthError(): boolean {
    return this.status === 401;
  }

  get isPermissionError(): boolean {
    return this.status === 403;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }

  get isConflict(): boolean {
    return this.status === 409;
  }

  /** Server-rejected business rules, which usually need a user-facing explanation. */
  get isBusinessRule(): boolean {
    return this.status === 409 || this.status === 422 || this.status === 410;
  }

  get isValidationError(): boolean {
    return this.status === 400 || this.status === 422;
  }

  /** Field-keyed messages, for rendering inline form errors. */
  get fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const [key, value] of Object.entries(this.details)) {
      if (typeof value === 'string') out[key] = value;
    }
    return out;
  }

  /** A short line suitable for a banner. */
  get displayMessage(): string {
    return this.isNetworkError
      ? 'Cannot reach the server. Check your connection and try again.'
      : this.message;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

/** Human-readable text for any caught value. */
export function toDisplayMessage(value: unknown): string {
  if (isApiError(value)) return value.displayMessage;
  if (value instanceof Error) return value.message;
  return 'Something went wrong. Please try again.';
}
