/**
 * Root layout.
 *
 * Owns the provider stack, the splash gate while the session is restored, and the
 * offline banner. Route-level role gating lives in the `(auth)`, `(customer)`,
 * `(partner)` and `(ops)` group layouts, which is where expo-router's redirects apply.
 */

import { useEffect } from 'react';
import { StatusBar } from 'expo-status-bar';
import { Stack, useRouter, useSegments } from 'expo-router';
import { QueryClientProvider } from '@tanstack/react-query';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { GestureHandlerRootView } from 'react-native-gesture-handler';

import 'react-native-reanimated';

import { queryClient } from '@/query/queryClient';
import { SessionProvider, useSession } from '@/auth/SessionProvider';
import { useNetworkStatus } from '@/hooks';
import { Banner, LoadingState, Screen } from '@/components/ui';

/**
 * Decides the landing route from the session.
 *
 * Kept out of the auth screens themselves so a session change anywhere redirects
 * consistently: no session, an incomplete profile, then one route per role.
 */
function RouteGate() {
  const { status, needsRegistration, isCustomer, isPartner, isStaff } = useSession();
  const router = useRouter();
  const segments = useSegments();

  useEffect(() => {
    if (status === 'initialising') return;

    const inAuthGroup = segments[0] === '(auth)';

    if (status === 'unauthenticated') {
      if (!inAuthGroup) router.replace('/(auth)/phone');
      return;
    }

    if (needsRegistration) {
      if (!inAuthGroup) {
        router.replace(isPartner ? '/(auth)/register/partner' : '/(auth)/register/customer');
      }
      return;
    }

    // Authenticated and complete: send them to the experience for their role.
    if (inAuthGroup) {
      if (isStaff) router.replace('/(ops)');
      else if (isPartner && !isCustomer) router.replace('/(partner)');
      else router.replace('/(customer)');
    }
  }, [status, needsRegistration, isCustomer, isPartner, isStaff, router, segments]);

  if (status === 'initialising') {
    return (
      <Screen scrollable={false} contentStyle={{ justifyContent: 'center' }}>
        <LoadingState label="Restoring your session" />
      </Screen>
    );
  }

  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: 'transparent' },
      }}>
      <Stack.Screen name="(auth)" />
      <Stack.Screen name="(customer)" />
      <Stack.Screen name="(partner)" />
      <Stack.Screen name="(ops)" />
      <Stack.Screen name="booking" />
      <Stack.Screen name="+not-found" />
    </Stack>
  );
}

/** Offline banner, rendered above the navigator so it is visible on every screen. */
function OfflineBanner() {
  const { isOnline, isChecking } = useNetworkStatus();
  if (isChecking || isOnline) return null;
  return (
    <Banner
      testID="offline-banner"
      tone="warning"
      message="You are offline. Actions that change bookings will fail until you reconnect."
    />
  );
}

export default function RootLayout() {
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <QueryClientProvider client={queryClient}>
          <SessionProvider>
            <StatusBar style="auto" />
            <OfflineBanner />
            <RouteGate />
          </SessionProvider>
        </QueryClientProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
