/**
 * Shared booking routes.
 *
 * These screens live outside the `(customer)`, `(partner)` and `(ops)` groups because
 * more than one role legitimately opens them: a partner follows an offer into the job,
 * and ops opens a booking from the job board or the exception queue. This layout is
 * therefore what makes `booking` a route at all, and it guards authentication for
 * everyone while gating the quote funnel - which only a customer can drive - on role.
 */

import { Redirect, Stack, usePathname } from 'expo-router';

import { useSession } from '@/auth/SessionProvider';

/**
 * Routes that build a booking.
 *
 * Only a customer has the addresses, vehicles and the intent these screens assume;
 * for anyone else the funnel renders a form whose every request is rejected.
 */
const CUSTOMER_ONLY_ROUTES = new Set([
  '/booking/quote',
  '/booking/quote-review',
  '/booking/confirm',
]);

export default function BookingLayout() {
  const { status, isCustomer, isPartner, isStaff, needsRegistration } = useSession();
  const pathname = usePathname();

  // Every role flag is false while the session is still being restored, so without
  // this the checks below would treat an in-flight session as signed out and bounce
  // the user to the login screen.
  if (status === 'initialising') return null;

  if (status === 'unauthenticated') return <Redirect href="/(auth)/phone" />;

  if (needsRegistration) {
    return <Redirect href={isPartner ? '/(auth)/register/partner' : '/(auth)/register/customer'} />;
  }

  if (!isCustomer && !isPartner && !isStaff) return <Redirect href="/(auth)/phone" />;

  if (!isCustomer && CUSTOMER_ONLY_ROUTES.has(pathname)) {
    return <Redirect href={isStaff ? '/(ops)' : '/(partner)'} />;
  }

  return <Stack screenOptions={{ headerShown: false }} />;
}