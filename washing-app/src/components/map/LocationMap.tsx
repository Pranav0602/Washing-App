/**
 * Map surface for native.
 *
 * `react-native-maps` cannot be imported on web: its barrel pulls in the Fabric
 * specs, which call `codegenNativeComponent` from `react-native`, and on web that
 * specifier is aliased to `react-native-web`, which does not export it. The web
 * build resolves `LocationMap.web.tsx` instead, so the import never reaches Metro
 * for the web bundle.
 *
 * Callers pass a plain coordinate and get press/drag callbacks, so no screen needs
 * to know which platform it is on or reach for a `MapView` ref.
 */

import { useEffect, useMemo, useRef } from 'react';
import { StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';
import MapView, { Marker, PROVIDER_GOOGLE } from 'react-native-maps';

export interface Coordinate {
  latitude: number;
  longitude: number;
}

export interface LocationMapProps {
  /** Shown under the pin, and used as the map frame when no pin is set yet. */
  coordinate: Coordinate;
  /** Region delta for the initial frame and for programmatic pans. */
  span?: number;
  /** Lets the customer reposition the pin by dragging it. */
  draggable?: boolean;
  onPress?: (coordinate: Coordinate) => void;
  onDragEnd?: (coordinate: Coordinate) => void;
  style?: StyleProp<ViewStyle>;
}

export const MAP_HEIGHT = 200;

const PAN_DURATION_MS = 350;

export function LocationMap({
  coordinate,
  span = 0.01,
  draggable = false,
  onPress,
  onDragEnd,
  style,
}: LocationMapProps) {
  const mapRef = useRef<MapView | null>(null);
  const isFirstRender = useRef(true);

  const region = useMemo(
    () => ({
      latitude: coordinate.latitude,
      longitude: coordinate.longitude,
      latitudeDelta: span,
      longitudeDelta: span,
    }),
    [coordinate.latitude, coordinate.longitude, span],
  );

  // Pan to the new pin instead of letting the `region` prop snap the camera back,
  // which is what makes "use my current location" feel like it glides.
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    mapRef.current?.animateToRegion(region, PAN_DURATION_MS);
  }, [region]);

  return (
    <View style={[styles.frame, style]}>
      <MapView
        ref={mapRef}
        style={StyleSheet.absoluteFill}
        provider={PROVIDER_GOOGLE}
        initialRegion={region}
        onPress={(event) => onPress?.(event.nativeEvent.coordinate)}
      >
        <Marker
          coordinate={coordinate}
          draggable={draggable}
          onDragEnd={(event) => onDragEnd?.(event.nativeEvent.coordinate)}
        />
      </MapView>
    </View>
  );
}

const styles = StyleSheet.create({
  frame: {
    height: MAP_HEIGHT,
    borderRadius: 12,
    overflow: 'hidden',
  },
});