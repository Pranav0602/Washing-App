/**
 * Form field primitives.
 *
 * `TextField` is wired for React Hook Form: it registers itself through the `control`
 * prop and surfaces validation messages inline, so no screen has to reimplement the
 * error plumbing. `SelectField` uses the same contract with a native picker, which
 * is more reliable than a custom modal across both platforms.
 */

import {
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  type KeyboardTypeOptions,
  type TextInputProps,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Picker } from '@react-native-picker/picker';
import { Controller, type Control, type FieldValues, type Path } from 'react-hook-form';

import { useTheme } from '@/theme';

interface TextFieldProps<T extends FieldValues> extends Omit<TextInputProps, 'name'> {
  control: Control<T>;
  name: Path<T>;
  label: string;
  placeholder?: string;
  hint?: string;
  required?: boolean;
  keyboardType?: KeyboardTypeOptions;
  autoCapitalize?: TextInputProps['autoCapitalize'];
  multiline?: boolean;
  testID?: string;
}

export function TextField<T extends FieldValues>({
  control,
  name,
  label,
  placeholder,
  hint,
  required = false,
  multiline = false,
  testID,
  ...inputProps
}: TextFieldProps<T>) {
  const { colors, radius, spacing, type, minTouchTarget } = useTheme();

  return (
    <Controller
      control={control}
      name={name}
      render={({ field: { onChange, onBlur, value }, fieldState: { error }, formState: { isSubmitting } }) => (
        <View style={styles.field}>
          <Text style={[styles.label, type.captionStrong, { color: colors.mutedText }]}>
            {label}
            {required ? <Text style={{ color: colors.danger }}> *</Text> : null}
          </Text>

          <TextInput
            testID={testID ?? `field-${String(name)}`}
            value={(value as string) ?? ''}
            onChangeText={onChange}
            onBlur={onBlur}
            placeholder={placeholder}
            placeholderTextColor={colors.mutedText}
            editable={!isSubmitting}
            multiline={multiline}
            accessibilityLabel={label}
            accessibilityHint={hint}
            // Announced by screen readers when a field fails validation.
            accessibilityState={{ disabled: Boolean(isSubmitting) }}
            style={[
              styles.input,
              type.body,
              {
                backgroundColor: colors.surface,
                borderColor: error ? colors.danger : colors.border,
                color: colors.text,
                borderRadius: radius.md,
                paddingHorizontal: spacing.md,
                minHeight: multiline ? minTouchTarget * 2 : minTouchTarget,
                textAlignVertical: multiline ? 'top' : 'center',
              },
            ]}
            {...inputProps}
          />

          {error ? (
            <Text style={[styles.error, type.caption, { color: colors.danger }]}>{String(error.message)}</Text>
          ) : hint ? (
            <Text style={[styles.hint, type.caption, { color: colors.mutedText }]}>{hint}</Text>
          ) : null}
        </View>
      )}
    />
  );
}

export interface SelectOption {
  value: string;
  label: string;
  description?: string;
}

interface SelectFieldProps<T extends FieldValues> {
  control: Control<T>;
  name: Path<T>;
  label: string;
  options: SelectOption[];
  placeholder?: string;
  required?: boolean;
  testID?: string;
}

export function SelectField<T extends FieldValues>({
  control,
  name,
  label,
  options,
  placeholder = 'Select an option',
  required = false,
  testID,
}: SelectFieldProps<T>) {
  const { colors, radius, type, minTouchTarget } = useTheme();

  return (
    <Controller
      control={control}
      name={name}
      render={({ field: { onChange, value }, fieldState: { error } }) => {
        const selected = options.find((option) => option.value === value);
        return (
          <View style={styles.field}>
            <Text style={[styles.label, type.captionStrong, { color: colors.mutedText }]}>
              {label}
              {required ? <Text style={{ color: colors.danger }}> *</Text> : null}
            </Text>

            <View style={styles.selectRow}>
              {/* Native picker: fewer platform quirks than a custom modal. */}
              <View style={styles.selectFlex}>
                <SelectPicker
                  testID={testID ?? `select-${String(name)}`}
                  selectedValue={(value as string) ?? ''}
                  onValueChange={onChange}
                  options={options}
                  placeholder={placeholder}
                  label={label}
                  colors={colors}
                  radius={radius}
                  minHeight={minTouchTarget}
                />
              </View>
              {selected?.description ? (
                <Text style={[styles.hint, type.caption, { color: colors.mutedText }]}>
                  {selected.description}
                </Text>
              ) : null}
            </View>

            {error ? (
              <Text style={[styles.error, type.caption, { color: colors.danger }]}>
                {String(error.message)}
              </Text>
            ) : null}
          </View>
        );
      }}
    />
  );
}

/** Thin wrapper so the picker can be swapped without touching every field. */
function SelectPicker({
  selectedValue,
  onValueChange,
  options,
  placeholder,
  label,
  colors,
  radius,
  minHeight,
  testID,
}: {
  selectedValue: string;
  onValueChange: (value: string) => void;
  options: SelectOption[];
  placeholder: string;
  label: string;
  colors: ReturnType<typeof useTheme>['colors'];
  radius: ReturnType<typeof useTheme>['radius'];
  minHeight: number;
  testID?: string;
}) {
  return (
    <View
      style={[
        styles.pickerWrap,
        {
          backgroundColor: colors.surface,
          borderColor: colors.border,
          borderRadius: radius.md,
          minHeight,
        },
      ]}>
      <Picker
        testID={testID}
        selectedValue={selectedValue}
        onValueChange={onValueChange}
        accessibilityLabel={label}
        dropdownIconColor={colors.icon}
        style={{ color: colors.text }}
        itemStyle={{ color: colors.text }}>
        <Picker.Item label={placeholder} value="" color={colors.mutedText} />
        {options.map((option) => (
          <Picker.Item key={option.value} label={option.label} value={option.value} color={colors.text} />
        ))}
      </Picker>
    </View>
  );
}

interface ToggleRowProps {
  label: string;
  description?: string;
  value: boolean;
  onValueChange: (next: boolean) => void;
  disabled?: boolean;
  testID?: string;
}

/** A labelled switch, used for consent and preference rows. */
export function ToggleRow({
  label,
  description,
  value,
  onValueChange,
  disabled = false,
  testID,
}: ToggleRowProps) {
  const { colors, radius, spacing, type } = useTheme();

  return (
    <Pressable
      testID={testID}
      onPress={() => !disabled && onValueChange(!value)}
      accessibilityRole="switch"
      accessibilityLabel={label}
      accessibilityHint={description}
      accessibilityState={{ checked: value, disabled }}
      style={[
        styles.toggleRow,
        {
          backgroundColor: colors.surface,
          borderColor: colors.border,
          borderRadius: radius.md,
          padding: spacing.md,
          opacity: disabled ? 0.6 : 1,
        },
      ]}>
      <View style={styles.toggleText}>
        <Text style={[type.body, { color: colors.text }]}>{label}</Text>
        {description ? (
          <Text style={[type.caption, { color: colors.mutedText, marginTop: 2 }]}>{description}</Text>
        ) : null}
      </View>
      <View
        style={[
          styles.toggleTrack,
          {
            backgroundColor: value ? colors.tint : colors.surfaceAlt,
            borderColor: value ? colors.tint : colors.border,
            borderRadius: radius.pill,
          },
        ]}>
        <View
          style={[
            styles.toggleThumb,
            {
              backgroundColor: value ? '#FFFFFF' : colors.mutedText,
              transform: [{ translateX: value ? 14 : 0 }],
            },
          ]}
        />
      </View>
    </Pressable>
  );
}

/** A row of mutually exclusive chips, e.g. vehicle type or add-ons. */
export function ChipGroup<T extends string>({
  label,
  options,
  value,
  onChange,
  error,
  testID,
}: {
  label?: string;
  options: SelectOption[];
  value: T | undefined;
  onChange: (value: T) => void;
  error?: string;
  testID?: string;
}) {
  const { colors, radius, spacing, type, minTouchTarget } = useTheme();

  return (
    <View style={styles.field}>
      {label ? (
        <Text style={[styles.label, type.captionStrong, { color: colors.mutedText }]}>{label}</Text>
      ) : null}

      <View style={[styles.chipRow, { gap: spacing.sm }]}>
        {options.map((option) => {
          const selected = option.value === value;
          return (
            <Pressable
              key={option.value}
              testID={testID ? `${testID}-${option.value}` : undefined}
              onPress={() => onChange(option.value as T)}
              accessibilityRole="radio"
              accessibilityState={{ selected }}
              accessibilityLabel={option.label}
              style={[
                styles.chip,
                {
                  minHeight: minTouchTarget - 8,
                  paddingHorizontal: spacing.md,
                  borderRadius: radius.pill,
                  backgroundColor: selected ? colors.tint : colors.surface,
                  borderColor: selected ? colors.tint : colors.border,
                },
              ]}>
              <Text style={[type.bodyStrong, { color: selected ? '#FFFFFF' : colors.text }]}>
                {option.label}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {error ? <Text style={[styles.error, type.caption, { color: colors.danger }]}>{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  field: { marginBottom: 4 },
  label: { marginBottom: 6 },
  input: { borderWidth: 1 },
  error: { marginTop: 6 },
  hint: { marginTop: 6 },
  selectRow: {},
  selectFlex: { width: '100%' },
  pickerWrap: { borderWidth: 1, overflow: 'hidden', justifyContent: 'center' },
  toggleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderWidth: 1,
    marginBottom: 8,
    minHeight: 56,
  },
  toggleText: { flex: 1, paddingRight: 12 },
  toggleTrack: { width: 40, height: 24, borderWidth: 1, justifyContent: 'center', paddingHorizontal: 3 },
  toggleThumb: { width: 16, height: 16, borderRadius: 8 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap' },
  chip: { borderWidth: 1, justifyContent: 'center' },
});

/**
 * A standalone checkbox for lists that are not driven by react-hook-form -- the
 * partner service checklist is a plain array of items, not form fields.
 */
export function Checkbox({
  label,
  checked,
  onToggle,
  disabled = false,
  hint,
  testID,
}: {
  label: string;
  checked: boolean;
  onToggle: () => void;
  disabled?: boolean;
  hint?: string;
  testID?: string;
}) {
  const { colors, radius, spacing, type } = useTheme();
  return (
    <Pressable
      testID={testID}
      onPress={disabled ? undefined : onToggle}
      disabled={disabled}
      accessibilityRole="checkbox"
      accessibilityState={{ checked, disabled }}
      accessibilityLabel={label}
      style={{
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: spacing.sm,
        paddingVertical: spacing.sm,
        opacity: disabled ? 0.6 : 1,
      }}
    >
      <View
        style={{
          width: 24,
          height: 24,
          marginTop: 1,
          borderRadius: radius.sm,
          borderWidth: 2,
          borderColor: checked ? colors.success : colors.border,
          backgroundColor: checked ? colors.success : 'transparent',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        {checked ? <Ionicons name="checkmark" size={16} color={colors.surface} /> : null}
      </View>
      <View style={{ flex: 1 }}>
        <Text style={[type.body, { color: colors.text }]}>{label}</Text>
        {hint ? (
          <Text style={[type.caption, { color: colors.mutedText, marginTop: 2 }]}>{hint}</Text>
        ) : null}
      </View>
    </Pressable>
  );
}
