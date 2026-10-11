import { useRouter } from 'expo-router';

import { Button, EmptyState, Screen } from '@/components/ui';

/**
 * Catch-all for unmatched routes. Expo Router requires this file to exist for the
 * `+not-found` screen declared in the root layout.
 */
export default function NotFoundScreen() {
  const router = useRouter();

  return (
    <Screen testID="not-found-screen">
      <EmptyState
        title="Page not found"
        message="That link is invalid or the page has moved."
        // There is no app/index.tsx, so '/' would resolve back to this very screen.
        // The root gate turns '/(auth)/phone' into the right landing route for the
        // session, which is what "go home" actually means here.
        action={{ label: 'Go home', onPress: () => router.replace('/(auth)/phone') }}
      />
      <Button
        label="Go back"
        variant="secondary"
        onPress={() => router.back()}
        style={{ marginTop: 8 }}
        testID="not-found-back"
      />
    </Screen>
  );
}
