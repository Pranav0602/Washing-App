/**
 * Design tokens.
 *
 * Built on the template's light/dark colour pair so the preserved
 * `useThemeColor` hook keeps working, extended with the semantic roles the booking
 * lifecycle needs (success, warning, danger, info) plus spacing, radii and type scale.
 */

import { Platform } from 'react-native';

const brandLight = '#0a7ea4';
const brandDark = '#4fc3e8';

export interface ThemeColors {
  text: string;
  mutedText: string;
  background: string;
  surface: string;
  surfaceAlt: string;
  border: string;
  tint: string;
  icon: string;
  tabIconDefault: string;
  tabIconSelected: string;
  success: string;
  successSurface: string;
  warning: string;
  warningSurface: string;
  danger: string;
  dangerSurface: string;
  info: string;
  infoSurface: string;
  overlay: string;
}

export const Palette = {
  light: {
    text: '#11181C',
    mutedText: '#5A6670',
    background: '#F4F6F8',
    surface: '#FFFFFF',
    surfaceAlt: '#EDF1F4',
    border: '#D7DEE4',
    tint: brandLight,
    icon: '#687076',
    tabIconDefault: '#687076',
    tabIconSelected: brandLight,
    success: '#1B7A45',
    successSurface: '#E4F4EA',
    warning: '#8A5B00',
    warningSurface: '#FCF1DC',
    danger: '#B3261E',
    dangerSurface: '#FBE9E7',
    info: '#0B5FA5',
    infoSurface: '#E3F0FB',
    overlay: 'rgba(17, 24, 28, 0.45)',
  },
  dark: {
    text: '#ECEDEE',
    mutedText: '#A3ADB5',
    background: '#101315',
    surface: '#1A1F22',
    surfaceAlt: '#232A2E',
    border: '#333C42',
    tint: brandDark,
    icon: '#9BA1A6',
    tabIconDefault: '#9BA1A6',
    tabIconSelected: brandDark,
    success: '#5FD08A',
    successSurface: '#12301F',
    warning: '#F0C36D',
    warningSurface: '#33280F',
    danger: '#FF8A80',
    dangerSurface: '#3A1A18',
    info: '#7FC4F5',
    infoSurface: '#12293A',
    overlay: 'rgba(0, 0, 0, 0.6)',
  },
} satisfies Record<'light' | 'dark', ThemeColors>;

export const Spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

export const Radius = {
  sm: 8,
  md: 12,
  lg: 16,
  pill: 999,
} as const;

/**
 * Minimum touch target, per platform accessibility guidance. Interactive rows pad
 * their content out to this rather than relying on the visual size of the label.
 */
export const MIN_TOUCH_TARGET = 44;

export const Fonts = Platform.select({
  ios: { sans: 'System', mono: 'Menlo' },
  default: { sans: 'System', mono: 'monospace' },
  web: {
    sans: "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    mono: 'ui-monospace, SFMono-Regular, Menlo, monospace',
  },
})!;

export const Type = {
  display: { fontSize: 30, lineHeight: 36, fontWeight: '700' as const },
  title: { fontSize: 22, lineHeight: 28, fontWeight: '700' as const },
  heading: { fontSize: 17, lineHeight: 23, fontWeight: '600' as const },
  body: { fontSize: 15, lineHeight: 22, fontWeight: '400' as const },
  bodyStrong: { fontSize: 15, lineHeight: 22, fontWeight: '600' as const },
  caption: { fontSize: 13, lineHeight: 18, fontWeight: '400' as const },
  captionStrong: { fontSize: 13, lineHeight: 18, fontWeight: '600' as const },
  micro: { fontSize: 11, lineHeight: 15, fontWeight: '600' as const },
} as const;
