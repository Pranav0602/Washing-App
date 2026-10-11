/**
 * Customer tab layout.
 *
 * Guards the whole group: a non-customer is redirected out, so no customer screen can
 * be reached by navigating directly.
 */

import { Redirect, Tabs } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';

import { useSession } from '@/auth/SessionProvider';
import { useTheme } from '@/theme';

export default function CustomerLayout() {
  const { isCustomer, isPartner, isStaff, needsRegistration } = useSession();
  const { colors } = useTheme();

  // Registration is role-specific, so the role has to be resolved before the
  // incomplete-profile check: otherwise a partner with an unfinished profile is sent
  // to the customer form, which cannot create a partner account.
  if (!isCustomer) {
    if (needsRegistration) {
      return <Redirect href={isPartner ? '/(auth)/register/partner' : '/(auth)/register/customer'} />;
    }
    // A partner-only account belongs in the partner experience, per the PDF's
    // requirement that the two experiences stay distinct.
    if (isStaff) return <Redirect href="/(ops)" />;
    if (isPartner) return <Redirect href="/(partner)" />;
    return <Redirect href="/(auth)/phone" />;
  }

  if (needsRegistration) return <Redirect href="/(auth)/register/customer" />;

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.tint,
        tabBarInactiveTintColor: colors.icon,
        tabBarStyle: { backgroundColor: colors.surface, borderTopColor: colors.border },
      }}>
      <Tabs.Screen
        name="index"
        options={{
          title: 'Home',
          tabBarIcon: ({ color, size }) => <Ionicons name="home-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="bookings"
        options={{
          title: 'Bookings',
          tabBarIcon: ({ color, size }) => <Ionicons name="calendar-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="garage"
        options={{
          title: 'Garage',
          tabBarIcon: ({ color, size }) => <Ionicons name="car-sport-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="notifications"
        options={{
          title: 'Updates',
          tabBarIcon: ({ color, size }) => <Ionicons name="notifications-outline" size={size} color={color} />,
        }}
      />
      <Tabs.Screen
        name="profile"
        options={{
          title: 'Profile',
          tabBarIcon: ({ color, size }) => <Ionicons name="person-outline" size={size} color={color} />,
        }}
      />
    </Tabs>
  );
}
