/**
 * Shared hooks.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import * as Network from 'expo-network';

/**
 * Online/offline state.
 *
 * Drives the offline banner. Note that this reports connectivity, not server
 * reachability: the API client still surfaces a network error when the device is
 * online but the API is unreachable, which is why screens show error states as well.
 */
export function useNetworkStatus(): { isOnline: boolean; isChecking: boolean } {
  const [isOnline, setIsOnline] = useState(true);
  const [isChecking, setIsChecking] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const read = async () => {
      try {
        const state = await Network.getNetworkStateAsync();
        if (!cancelled) setIsOnline(Boolean(state.isConnected));
      } catch {
        // If the check itself fails, assume online and let requests surface errors.
        if (!cancelled) setIsOnline(true);
      } finally {
        if (!cancelled) setIsChecking(false);
      }
    };

    void read();
    const subscription = Network.addNetworkStateListener(() => {
      void read();
    });

    return () => {
      cancelled = true;
      subscription.remove();
    };
  }, []);

  return { isOnline, isChecking };
}

/**
 * A ticking countdown.
 *
 * Used for the live offer timer. Pauses when `active` is false so a backgrounded
 * screen does not keep the timer running.
 */
export function useCountdown(secondsRemaining: number | null, active = true): number {
  const [remaining, setRemaining] = useState(secondsRemaining ?? 0);
  const [anchoredSeconds, setAnchoredSeconds] = useState(secondsRemaining);

  // A new duration from the server wins outright, so resyncing during render keeps
  // the tick effect free of state writes.
  if (anchoredSeconds !== secondsRemaining) {
    setAnchoredSeconds(secondsRemaining);
    setRemaining(secondsRemaining ?? 0);
  }

  useEffect(() => {
    if (!active || secondsRemaining === null) return;

    // Measure against the wall clock inside the callback so a backgrounded app
    // catches up on resume instead of losing the elapsed seconds.
    let previousTick = Date.now();
    const interval = setInterval(() => {
      const currentTick = Date.now();
      const elapsed = Math.round((currentTick - previousTick) / 1000);
      previousTick = currentTick;
      if (elapsed > 0) setRemaining((previous) => Math.max(previous - elapsed, 0));
    }, 1000);

    return () => clearInterval(interval);
  }, [active, secondsRemaining]);

  return remaining;
}

/**
 * Periodic polling for an active job.
 *
 * Only runs while `enabled` is true, so a completed or backgrounded booking stops
 * polling. The interval is deliberately modest; push handles the rest.
 */
export function usePolling(callback: () => void, intervalMs: number, enabled = true): void {
  const savedCallback = useRef(callback);

  useEffect(() => {
    savedCallback.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!enabled || intervalMs <= 0) return;
    const interval = setInterval(() => savedCallback.current(), intervalMs);
    return () => clearInterval(interval);
  }, [enabled, intervalMs]);
}

/** Debounce a rapidly changing value, e.g. a search field. */
export function useDebouncedValue<T>(value: T, delayMs = 400): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}

/**
 * Run an async action, tracking loading and error state.
 *
 * Returns a stable callback so it is safe to pass directly to a button's onPress.
 */
export function useAsyncAction<Args extends unknown[]>(
  action: (...args: Args) => Promise<void>,
): {
  run: (...args: Args) => Promise<void>;
  isLoading: boolean;
  error: unknown;
  reset: () => void;
} {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = useCallback(
    async (...args: Args) => {
      setIsLoading(true);
      setError(null);
      try {
        await action(...args);
      } catch (caught) {
        if (mounted.current) setError(caught);
        throw caught;
      } finally {
        if (mounted.current) setIsLoading(false);
      }
    },
    [action],
  );

  const reset = useCallback(() => setError(null), []);

  return { run, isLoading, error, reset };
}
