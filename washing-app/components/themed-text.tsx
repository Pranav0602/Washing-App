/**
 * Preserved from the Expo template. Kept so the starter components still compile
 * against the project theme while the app's own design tokens live in `src/theme`.
 */

import { Text, type TextProps } from 'react-native';

import { Palette } from '@/theme/tokens';

export type ThemedTextProps = TextProps & {
  lightColor?: string;
  darkColor?: string;
  type?: 'default' | 'title' | 'defaultSemiBold' | 'subtitle' | 'link';
};

export function ThemedText({
  style,
  lightColor,
  darkColor,
  type = 'default',
  ...rest
}: ThemedTextProps) {
  const color = lightColor ?? darkColor ?? Palette.light.text;

  return (
    <Text
      style={[
        { color },
        type === 'default' ? styles.default : undefined,
        type === 'title' ? styles.title : undefined,
        type === 'defaultSemiBold' ? styles.defaultSemiBold : undefined,
        type === 'subtitle' ? styles.subtitle : undefined,
        type === 'link' ? styles.link : undefined,
        style,
      ]}
      {...rest}
    />
  );
}

const styles = {
  default: { fontSize: 16, lineHeight: 24 },
  defaultSemiBold: { fontSize: 16, lineHeight: 24, fontWeight: '600' as const },
  title: { fontSize: 32, fontWeight: 'bold' as const, lineHeight: 32 },
  subtitle: { fontSize: 20, fontWeight: 'bold' as const },
  link: { lineHeight: 30, fontSize: 16, color: Palette.light.tint },
};
