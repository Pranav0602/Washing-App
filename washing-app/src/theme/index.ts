/**
 * Typed theme hook.
 *
 * Wraps the template's `useThemeColor` so components read one object rather than
 * threading light/dark pairs through every prop.
 */

import { useColorScheme } from '../../hooks/use-color-scheme';

import {
  Palette,
  Radius,
  Spacing,
  Type,
  MIN_TOUCH_TARGET,
  type ThemeColors,
} from './tokens';

export interface Theme {
  colors: ThemeColors;
  spacing: typeof Spacing;
  radius: typeof Radius;
  type: typeof Type;
  minTouchTarget: number;
  isDark: boolean;
}

export function useTheme(): Theme {
  const scheme = useColorScheme();
  const isDark = scheme === 'dark';
  return {
    colors: isDark ? Palette.dark : Palette.light,
    spacing: Spacing,
    radius: Radius,
    type: Type,
    minTouchTarget: MIN_TOUCH_TARGET,
    isDark,
  };
}
