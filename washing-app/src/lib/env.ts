/**
 * Environment configuration.
 *
 * The API base URL is read from `EXPO_PUBLIC_API_URL` and validated at startup.
 * Nothing in the app hardcodes a host: a missing or malformed URL fails loudly on
 * boot rather than producing confusing network errors later.
 *
 * Only `EXPO_PUBLIC_*` variables are inlined into the bundle by Expo, and this app
 * deliberately holds no secrets on the client.
 */

const DEFAULT_PORT = 8000;

function readApiUrl(): string {
  const raw = process.env.EXPO_PUBLIC_API_URL;

  if (!raw || raw.trim() === '') {
    if (__DEV__) {
      // A physical device cannot reach the host via localhost, and Android emulators
      // map it to 10.0.2.2. Remind the developer instead of failing silently.
      console.warn(
        '[config] EXPO_PUBLIC_API_URL is not set. Copy .env.example to .env and set it.\n' +
          `         Android emulator: http://10.0.2.2:${DEFAULT_PORT}\n` +
          `         iOS simulator / web: http://localhost:${DEFAULT_PORT}`,
      );
    }
    throw new Error(
      'EXPO_PUBLIC_API_URL is required. Copy .env.example to .env and set it to your API base URL.',
    );
  }

  let parsed: URL;
  try {
    parsed = new URL(raw.trim());
  } catch {
    throw new Error(
      `EXPO_PUBLIC_API_URL is not a valid URL (received ${JSON.stringify(raw)}).`,
    );
  }

  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error(
      `EXPO_PUBLIC_API_URL must use http or https (received ${parsed.protocol}).`,
    );
  }

  // Normalise so the client never produces a double slash before a path segment.
  return parsed.toString().replace(/\/+$/, '');
}

export const config = {
  apiBaseUrl: readApiUrl(),
  apiPrefix: '/api/v1',
  appEnv: process.env.EXPO_PUBLIC_ENV ?? (__DEV__ ? 'development' : 'production'),
  enableEvidenceUploads: process.env.EXPO_PUBLIC_ENABLE_EVIDENCE_UPLOADS !== 'false',
} as const;

if (__DEV__) {
  // The single most common misconfiguration is pointing the app at the wrong host
  // (for example 10.0.2.2 from web, where it is unroutable). That fails as a
  // connection *timeout* rather than an obvious error, so print the resolved target
  // once at startup: it makes a wrong host visible immediately instead of after a
  // 20-second wait per attempt.
  console.warn(
    `[config] API base URL: ${config.apiBaseUrl}${config.apiPrefix}  (EXPO_PUBLIC_API_URL=${process.env.EXPO_PUBLIC_API_URL ?? ''})`,
  );
}

export type AppConfig = typeof config;
