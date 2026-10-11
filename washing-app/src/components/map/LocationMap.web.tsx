/**
 * Map surface for web.
 *
 * `react-native-maps` has no web implementation, so the native map cannot be
 * rendered here: importing it pulls in the Fabric specs and fails at module load
 * because `codegenNativeComponent` does not exist on `react-native-web`. This file
 * replaces it so the web bundle never reaches that import.
 *
 * The pin still has to be settable, so tapping the panel nudges it to a nearby
 * coordinate; the coordinates stay the source of truth for the saved address.
 */

import { useCallback } from 'react';
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native';

import { useTheme } from '@/theme';
import type { LocationMapProps } from './LocationMap';

export const MAP_HEIGHT = 200;

/** Each tap moves the pin by roughly the visible span. */
const TAP_STEP_DEGREES = 0.005;

export function LocationMap({ coordinate, onPress, style }: LocationMapProps) {
  const { colors, spacing, type } = useTheme();

  const pickNearby = useCallback(() => {
    if (!onPress) return;
    onPress({
      latitude: Number((coordinate.latitude + TAP_STEP_DEGREES).toFixed(4)),
      longitude: Number((coordinate.longitude + TAP_STEP_DEGREES).toFixed(4)),
    });
  }, [coordinate.latitude, coordinate.longitude, onPress]);

  const { latitude, longitude } = coordinate;
  const openInMaps = useCallback(() => {
    void Linking.openURL(
      `https://www.google.com/maps/search/?api=1&query=${latitude},${longitude}`,
    );
  }, [latitude, longitude]);

  return (
    <View
      testID="location-map-web"
      style={[
        styles.frame,
        { backgroundColor: colors.surfaceAlt, borderColor: colors.border },
        style,
      ]}>
      <View style={styles.center}>
        <Text style={[type.heading, { color: colors.text }]}>
          {latitude.toFixed(4)}, {longitude.toFixed(4)}
        </Text>
        <Text style={[type.caption, { color: colors.mutedText, marginTop: spacing.xs }]}>
          {onPress
            ? 'Tap to move the pin, or edit the coordinates above.'
            : 'Map preview is not available in the browser.'}
        </Text>
        <Pressable onPress={openInMaps} hitSlop={8} style={{ marginTop: spacing.md }}>
          <Text style={[type.captionStrong, { color: colors.tint }]}>Open in Google Maps</Text>
        </Pressable>
      </View>
      {onPress ? (
        <Pressable
          accessibilityLabel="Move pin"
          onPress={pickNearby}
          style={StyleSheet.absoluteFill}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  frame: {
    height: MAP_HEIGHT,
    borderRadius: 12,
    borderWidth: 1,
    justifyContent: 'center',
    paddingHorizontal: 16,
  },
  center: {
    alignItems: 'center',
  },
});