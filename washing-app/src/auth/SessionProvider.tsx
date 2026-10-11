/**
 * Session state.
 *
 * Holds only what authentication needs: the access token (in memory), the user and
 * their roles. Everything else is server state and belongs to TanStack Query.
 *
 * The refresh path is single-flight: if several requests get a 401 at once they all
 * wait on one refresh rather than firing several, because a second refresh with the
 * same rotated token would be treated as a replay and revoke the whole token family.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';

import { authApi, meApi } from '@/api/endpoints';
import type { AuthSession, Role, User } from '@/api/types';
import { configureApiClient, type RefreshOutcome } from '@/api/client';
import { ApiError } from '@/lib/apiError';
import { resetQueryClient } from '@/query/queryClient';

import { tokenStorage } from './tokenStorage';

export type SessionStatus = 'initialising' | 'authenticated' | 'unauthenticated';

export interface SessionValue {
  status: SessionStatus;
  user: User | null;
  roles: Role[];
  accessToken: string | null;
  /** True when a phone was verified but the profile is incomplete. */
  needsRegistration: boolean;
  isCustomer: boolean;
  isPartner: boolean;
  isStaff: boolean;
  signInWithOtp: (challengeId: string, code: string) => Promise<AuthSession>;
  signOut: () => Promise<void>;
  /** Re-read the user after registration or a profile change. */
  refreshUser: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>('initialising');
  const [user, setUser] = useState<User | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);

  // Refs, not state: the API client reads these synchronously on every request.
  const accessTokenRef = useRef<string | null>(null);
  const refreshInFlight = useRef<Promise<RefreshOutcome> | null>(null);
  const sessionEndedRef = useRef(false);

  const applySession = useCallback((session: AuthSession) => {
    accessTokenRef.current = session.access_token;
    setAccessToken(session.access_token);
    setUser(session.user);
    setStatus('authenticated');
    void tokenStorage.setRefreshToken(session.refresh_token);
  }, []);

  const endSession = useCallback(() => {
    accessTokenRef.current = null;
    refreshInFlight.current = null;
    sessionEndedRef.current = true;
    // Server state is per-account. Without this the next person to sign in on this
    // device is served the previous user's cached bookings, addresses and payouts.
    resetQueryClient();
    setAccessToken(null);
    setUser(null);
    setStatus('unauthenticated');
    void tokenStorage.clearRefreshToken();
  }, []);

  // Register the client hooks once. They close over the refs above, so they always
  // see current values without being re-created on every render.
  useEffect(() => {
    configureApiClient({
      getAccessToken: () => accessTokenRef.current,
      refreshAccessToken: async (): Promise<RefreshOutcome> => {
        // Single-flight: concurrent 401s share one refresh. Returning the same promise
        // is safe because the refresh call itself is unauthenticated and therefore
        // never re-enters this handler.
        if (refreshInFlight.current) return refreshInFlight.current;

        const attempt = (async (): Promise<RefreshOutcome> => {
          const refreshToken = await tokenStorage.getRefreshToken();
          if (!refreshToken) return 'expired';

          try {
            const session = await authApi.refresh(refreshToken);
            applySession(session);
            return 'refreshed';
          } catch (error) {
            // A definitive rejection means the session cannot be recovered. A
            // network blip is different: keep the session and let the user retry.
            if (error instanceof ApiError && error.isNetworkError) return 'offline';
            return 'expired';
          } finally {
            refreshInFlight.current = null;
          }
        })();

        refreshInFlight.current = attempt;
        return attempt;
      },
      onSessionExpired: () => {
        sessionEndedRef.current = true;
        endSession();
      },
    });
  }, [applySession, endSession]);

  // Bootstrap from a stored refresh token on cold start.
  useEffect(() => {
    let cancelled = false;

    (async () => {
      const refreshToken = await tokenStorage.getRefreshToken();
      if (!refreshToken) {
        if (!cancelled) setStatus('unauthenticated');
        return;
      }

      try {
        const session = await authApi.refresh(refreshToken);
        if (!cancelled) applySession(session);
      } catch {
        if (!cancelled) endSession();
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [applySession, endSession]);

  const signInWithOtp = useCallback(
    async (challengeId: string, code: string) => {
      const session = await authApi.verifyOtp(challengeId, code);
      sessionEndedRef.current = false;
      applySession(session);
      return session;
    },
    [applySession],
  );

  const signOut = useCallback(async () => {
    const refreshToken = await tokenStorage.getRefreshToken();
    // Revoke server-side, but never block sign-out on the network.
    if (refreshToken) {
      try {
        await authApi.logout(refreshToken);
      } catch {
        // Ignored deliberately: the local session is cleared either way.
      }
    }
    endSession();
  }, [endSession]);

  const refreshUser = useCallback(async () => {
    if (!accessTokenRef.current) return;
    try {
      const me = await meApi.get();
      setUser(me);
    } catch {
      // Keep the existing user object: a transient failure is not a reason to sign
      // the customer out mid-flow.
    }
  }, []);

  const value = useMemo<SessionValue>(() => {
    const roles = user?.roles ?? [];
    const isStaff = roles.includes('ops') || roles.includes('admin');
    return {
      status,
      user,
      roles,
      accessToken,
      // Staff are exempt. They are provisioned out of band and the registration
      // endpoints refuse them outright ("Staff accounts do not register as
      // customers"), so an incomplete profile must not route them to a form that
      // can only ever return 403 - that wedges them out of the app entirely.
      needsRegistration:
        status === 'authenticated' && user !== null && !user.account_complete && !isStaff,
      isCustomer: roles.includes('customer'),
      isPartner: roles.includes('partner'),
      isStaff,
      signInWithOtp,
      signOut,
      refreshUser,
    };
  }, [accessToken, refreshUser, signInWithOtp, signOut, status, user]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const context = useContext(SessionContext);
  if (!context) throw new Error('useSession must be used inside a SessionProvider.');
  return context;
}
