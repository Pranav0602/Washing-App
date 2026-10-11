/**
 * The TanStack Query client.
 *
 * Defaults are chosen for a service app on a mobile network: short stale windows so
 * job status stays honest, no refetch on window focus for polling-driven screens (they
 * set their own interval), and bounded retries so a business-rule 4xx is not retried.
 */

import { QueryClient } from '@tanstack/react-query';

import { ApiError } from '@/lib/apiError';

/** Retry only transport-level and 5xx failures; never a rejected request. */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError) {
    if (error.isNetworkError) return failureCount < 2;
    if (error.status >= 500) return failureCount < 2;
    return false;
  }
  return failureCount < 1;
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      gcTime: 5 * 60_000,
      retry: shouldRetry,
      refetchOnWindowFocus: false,
      refetchOnReconnect: true,
    },
    mutations: {
      // A failed mutation is reported to the user; silent retries would hide the
      // one thing they most need to see.
      retry: false,
    },
  },
});

export function resetQueryClient(): void {
  queryClient.clear();
}
