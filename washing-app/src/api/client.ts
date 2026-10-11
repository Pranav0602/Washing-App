/**
 * The only module in the app that performs network requests.
 *
 * Screens never build URLs, never call fetch, and never see a raw Response.
 * Everything they get is a parsed DTO or an `ApiError`.
 *
 * Responsibilities kept here so they cannot drift between screens:
 *  - base URL and `/api/v1` prefix from validated environment config
 *  - bearer token from the session, plus `X-Request-Id` for tracing
 *  - automatic `Idempotency-Key` on money and creation commands
 *  - single-flight access-token refresh on 401, with one replay of the original call
 *  - bounded retry, only for idempotent reads
 *  - request timeouts via AbortController
 *  - normalisation of every failure into `ApiError`
 */

import { ApiError, type ApiErrorEnvelope } from '@/lib/apiError';
import { config } from '@/lib/env';

export type HttpMethod = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';

export interface RequestOptions {
  method?: HttpMethod;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  /** Attach the bearer token. Defaults to true. */
  authenticated?: boolean;
  /** Supply an idempotency key. Generated automatically when the method needs one. */
  idempotencyKey?: string;
  /** Milliseconds before the request is aborted. */
  timeoutMs?: number;
  /** Do not retry this call even if it is a read. */
  noRetry?: boolean;
  /** Send as multipart instead of JSON. Used for photo uploads. */
  formData?: FormData;
  signal?: AbortSignal;
}

const DEFAULT_TIMEOUT_MS = 20_000;
const UPLOAD_TIMEOUT_MS = 60_000;
const MAX_ATTEMPTS = 3;

/** Methods whose semantics allow a safe automatic retry. */
const IDEMPOTENT_METHODS: ReadonlySet<HttpMethod> = new Set<HttpMethod>(['GET', 'PUT', 'DELETE']);

/** Methods that move money or create records and must never be blind-retried. */
const COMMAND_METHODS: ReadonlySet<HttpMethod> = new Set<HttpMethod>(['POST', 'PATCH']);

type TokenProvider = () => string | null;

/**
 * Outcome of a refresh attempt.
 *
 * `offline` is distinct from `expired` on purpose: a transport failure says nothing
 * about whether the session is still good, so it must not end it.
 */
export type RefreshOutcome = 'refreshed' | 'offline' | 'expired';

type RefreshHandler = () => Promise<RefreshOutcome>;

let getAccessToken: TokenProvider = () => null;
let onUnauthorized: RefreshHandler | null = null;
let onSessionExpired: (() => void) | null = null;

/** Wired up once by `AuthProvider`. */
export function configureApiClient(options: {
  getAccessToken: TokenProvider;
  refreshAccessToken: RefreshHandler;
  onSessionExpired: () => void;
}): void {
  getAccessToken = options.getAccessToken;
  onUnauthorized = options.refreshAccessToken;
  onSessionExpired = options.onSessionExpired;
}

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const base = `${config.apiBaseUrl}${config.apiPrefix}${path.startsWith('/') ? path : `/${path}`}`;
  if (!query) return base;

  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue;
    params.append(key, String(value));
  }
  const serialised = params.toString();
  return serialised ? `${base}?${serialised}` : base;
}

function newRequestId(): string {
  // RFC4122 v4, using the platform crypto API where available.
  const cryptoObj = (globalThis as { crypto?: Crypto }).crypto;
  if (cryptoObj?.randomUUID) return cryptoObj.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
    const random = (Math.random() * 16) | 0;
    const value = char === 'x' ? random : (random & 0x3) | 0x8;
    return value.toString(16);
  });
}

function newIdempotencyKey(): string {
  return newRequestId();
}

function backoffDelay(attempt: number): number {
  // Exponential with jitter, so retries from many clients do not synchronise.
  const base = 2 ** (attempt - 1) * 300;
  const jitter = Math.random() * 250;
  return Math.min(base + jitter, 4000);
}

async function parseError(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  const envelope = body as ApiErrorEnvelope | null;
  if (envelope?.error && typeof envelope.error === 'object') {
    return new ApiError(
      response.status,
      envelope.error.code ?? 'unknown_error',
      envelope.error.message ?? response.statusText,
      (envelope.error.details as Record<string, unknown>) ?? {},
      envelope.error.request_id ?? null,
    );
  }

  return new ApiError(
    response.status,
    `http_${response.status}`,
    response.statusText || 'Request failed',
    {},
    response.headers.get('X-Request-Id'),
  );
}

interface InternalOptions extends RequestOptions {
  /** Internal: this request already survived a refresh, so do not loop. */
  didRefresh?: boolean;
}

async function performRequest<T>(path: string, options: InternalOptions): Promise<T> {
  const {
    method = 'GET',
    body,
    query,
    authenticated = true,
    timeoutMs,
    formData,
    signal,
  } = options;

  const headers: Record<string, string> = {
    Accept: 'application/json',
    'X-Request-Id': newRequestId(),
  };

  let payload: BodyInit | undefined;
  if (formData) {
    // Content-Type is intentionally omitted: fetch sets the multipart boundary.
    payload = formData;
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }

  if (authenticated) {
    const token = getAccessToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  if (options.idempotencyKey && COMMAND_METHODS.has(method)) {
    headers['Idempotency-Key'] = options.idempotencyKey;
  }

  const controller = new AbortController();
  const budget = timeoutMs ?? (formData ? UPLOAD_TIMEOUT_MS : DEFAULT_TIMEOUT_MS);
  const timer = setTimeout(() => controller.abort(), budget);

  // Honour an externally supplied signal alongside our own timeout.
  const externalAbort = () => controller.abort();
  signal?.addEventListener('abort', externalAbort);

  try {
    const response = await fetch(buildUrl(path, query), {
      method,
      headers,
      body: payload,
      signal: controller.signal,
    });

    if (response.status === 204) return undefined as T;
    if (!response.ok) throw await parseError(response);

    const text = await response.text();
    return (text ? JSON.parse(text) : undefined) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;

    if (error instanceof Error && error.name === 'AbortError') {
      throw new ApiError(0, 'timeout', 'The request timed out. Please try again.');
    }
    // A fetch-level failure: offline, DNS, TLS, connection refused.
    throw new ApiError(0, 'network_error', 'Cannot reach the server.', {}, null);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', externalAbort);
  }
}

async function execute<T>(path: string, options: InternalOptions): Promise<T> {
  const method = options.method ?? 'GET';
  const retryable = IDEMPOTENT_METHODS.has(method) && !options.noRetry;

  let attempt = 0;
  while (true) {
    try {
      return await performRequest<T>(path, options);
    } catch (error) {
      const apiError = error as ApiError;

      // One refresh-and-replay on an expired access token.
      //
      // `getAccessToken() !== null` matters as much as the 401 itself: the refresh
      // call is itself an API call, so without this a 401 raised *while refreshing*
      // would recurse back into the single-flight refresh and await its own promise.
      // Refreshing is only meaningful while a session is actually held.
      if (
        apiError.isAuthError &&
        options.authenticated !== false &&
        !options.didRefresh &&
        getAccessToken() !== null
      ) {
        const outcome = onUnauthorized ? await onUnauthorized() : 'expired';
        if (outcome === 'refreshed') {
          return performRequest<T>(path, { ...options, didRefresh: true });
        }
        if (outcome === 'expired') {
          // The refresh was rejected outright, so the session is genuinely over.
          onSessionExpired?.();
          throw apiError;
        }
        // 'offline': the refresh never reached the server. Reporting the original 401
        // would tell the user to sign in again when the real problem is connectivity,
        // and ending the session here would throw away a perfectly good refresh token.
        throw new ApiError(
          0,
          'network_error',
          'Cannot reach the server.',
          {},
          apiError.requestId,
        );
      }

      const canRetry =
        retryable &&
        attempt + 1 < MAX_ATTEMPTS &&
        (apiError.isNetworkError || apiError.status >= 500);

      if (!canRetry) throw apiError;

      attempt += 1;
      await new Promise((resolve) => setTimeout(resolve, backoffDelay(attempt)));
    }
  }
}

export const apiClient = {
  get: <T>(path: string, options: Omit<RequestOptions, 'method' | 'body'> = {}) =>
    execute<T>(path, { ...options, method: 'GET' }),

  post: <T>(path: string, body?: unknown, options: Omit<RequestOptions, 'method' | 'body'> = {}) =>
    execute<T>(path, { ...options, method: 'POST', body }),

  patch: <T>(path: string, body?: unknown, options: Omit<RequestOptions, 'method' | 'body'> = {}) =>
    execute<T>(path, { ...options, method: 'PATCH', body }),

  put: <T>(path: string, body?: unknown, options: Omit<RequestOptions, 'method' | 'body'> = {}) =>
    execute<T>(path, { ...options, method: 'PUT', body }),

  delete: <T>(path: string, options: Omit<RequestOptions, 'method' | 'body'> = {}) =>
    execute<T>(path, { ...options, method: 'DELETE' }),

  /** Multipart upload, used for evidence photos. Never auto-retried. */
  upload: <T>(path: string, formData: FormData, options: Omit<RequestOptions, 'method' | 'body'> = {}) =>
    execute<T>(path, { ...options, method: 'POST', formData, noRetry: true }),

  /** Build an idempotency key for a command the caller is about to issue. */
  newIdempotencyKey,
};
