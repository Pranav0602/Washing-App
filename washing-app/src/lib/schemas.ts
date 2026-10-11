/**
 * Shared validation schemas.
 *
 * These are the single source of truth for form validity, so a screen cannot accept
 * input the API will reject. Messages are written to be actionable in the field.
 */

import { z } from 'zod';

import { VEHICLE_TYPE_OPTIONS } from '@/lib/format';

/** A boolean that must be true, typed as boolean so an unchecked default is legal. */
const mustAccept = (message: string) =>
  z.boolean().refine((value) => value === true, { message });

const SITE_TYPES = [
  { value: 'standalone_house', label: 'Independent house' },
  { value: 'apartment', label: 'Apartment' },
  { value: 'basement', label: 'Basement / parking' },
  { value: 'society', label: 'Society / gated community' },
  { value: 'commercial', label: 'Commercial site' },
] as const;

export const siteTypeOptions = SITE_TYPES.map((option) => ({ ...option }));
export const vehicleTypeOptions = VEHICLE_TYPE_OPTIONS;

/**
 * An optional vehicle year.
 *
 * `TextField` wires `onChangeText` straight into the form, so a numeric field always
 * arrives as a string - and as `''` once cleared. Declaring these as a plain
 * `z.number()` therefore rejected both a typed year and an emptied one. Coercing here
 * keeps every numeric input behaving the same way instead of special-casing fields.
 */
const optionalYear = z
  .union([z.string(), z.number()])
  .optional()
  .transform((value) => {
    if (value === undefined) return undefined;
    const trimmed = typeof value === 'string' ? value.trim() : value;
    if (trimmed === '') return undefined;
    const parsed = typeof trimmed === 'number' ? trimmed : Number(trimmed);
    // -1 sits outside the accepted range, so unparseable input lands on the same
    // "Enter a realistic year" message as an out-of-range year rather than leaking a
    // Zod type error to the user.
    return Number.isFinite(parsed) ? Math.trunc(parsed) : -1;
  })
  .pipe(
    z
      .number({ message: 'Enter a realistic year' })
      .int()
      .min(1950, 'Enter a realistic year')
      .max(new Date().getFullYear() + 1, 'Enter a realistic year')
      .optional(),
  );

// ------------------------------------------------------------------ phone

/**
 * Phone validation.
 *
 * Accepts 10 to 15 digits with an optional leading `+`. The backend normalises to
 * E.164, so the client only needs to reject obvious mistakes.
 */
export const phoneSchema = z
  .string()
  .trim()
  .min(1, 'Enter your phone number')
  .regex(/^\+?[0-9]{10,15}$/, 'Enter a valid phone number, e.g. 9876543210');

export const phoneSchemaForm = z.object({ phone: phoneSchema });

export type PhoneFormValues = z.infer<typeof phoneSchemaForm>;

// -------------------------------------------------------------------- otp

export const otpSchemaForm = z.object({
  code: z
    .string()
    .trim()
    .regex(/^[0-9]{4,10}$/, 'Enter the code you received'),
});

export type OtpFormValues = z.infer<typeof otpSchemaForm>;

// ------------------------------------------------------- customer profile

export const customerRegistrationSchema = z.object({
  full_name: z.string().trim().min(2, 'Enter your full name').max(200),

  // Line 2, state and postal code are optional on the wire but validated when given.
  line1: z.string().trim().min(3, 'Enter the street address').max(200),
  line2: z.string().trim().max(200).optional().default(''),
  city: z.string().trim().min(2, 'Enter the city').max(100),
  state: z.string().trim().max(100).optional().default(''),
  postal_code: z.string().trim().max(20).optional().default(''),

  // The coordinates are not a form input: they come from the device location or the
  // fallback pin the screen holds, and are spliced into the payload on submit.
  // Requiring them here would make the resolver fail on every submission.
  site_type: z.enum(['standalone_house', 'apartment', 'basement', 'society', 'commercial'], {
    message: 'Choose where the car will be washed',
  }),
  // Access detail is required in practice: the PDF has the partner rely on it on
  // arrival, so collecting it up front beats discovering it at the door.
  access_notes: z
    .string()
    .trim()
    .min(5, 'Tell your partner how to find and reach the car')
    .max(2000),
  parking_details: z.string().trim().max(1000).optional().default(''),
  property_approval: z.boolean().default(false),

  vehicle_type: z.enum(['car', 'suv', 'truck', 'van', 'bike', 'scooter'], {
    message: 'Choose the vehicle type',
  }),
  make: z.string().trim().min(1, 'Enter the make').max(64),
  model: z.string().trim().min(1, 'Enter the model').max(64),
  year: optionalYear,
  color: z.string().trim().max(32).optional().default(''),
  registration_number: z.string().trim().max(32).optional().default(''),

  terms: mustAccept('You must accept the terms to continue'),
  privacy: mustAccept('You must accept the privacy notice to continue'),
  evidence: z.boolean().default(true),
});

export type CustomerRegistrationValues = z.input<typeof customerRegistrationSchema>;

// ---------------------------------------------------------- partner signup

export const partnerRegistrationSchema = z.object({
  display_name: z.string().trim().min(2, 'Enter the name customers will see').max(120),
  bio: z.string().trim().max(1000).optional().default(''),
  skills: z.array(z.string()).default([]),
  payout_account_ref: z.string().trim().max(128).optional().default(''),

  terms: mustAccept('You must accept the partner terms'),
  privacy: mustAccept('You must accept the privacy notice'),
  // Precise location is only collected while on shift or on a job, and the partner
  // has to understand and accept that before applying.
  location: mustAccept('Location sharing is required while you are on shift or on a job'),
  evidence: z.boolean().default(true),
});

export type PartnerRegistrationValues = z.input<typeof partnerRegistrationSchema>;

// ----------------------------------------------------------------- vehicle

export const vehicleSchema = z.object({
  vehicle_type: z.enum(['car', 'suv', 'truck', 'van', 'bike', 'scooter']),
  make: z.string().trim().min(1, 'Enter the make').max(64),
  model: z.string().trim().min(1, 'Enter the model').max(64),
  year: optionalYear,
  color: z.string().trim().max(32).optional().default(''),
  registration_number: z.string().trim().max(32).optional().default(''),
});

export type VehicleValues = z.input<typeof vehicleSchema>;

export const addressSchema = z.object({
  label: z.string().trim().max(64).optional().default(''),
  line1: z.string().trim().min(3, 'Enter the street address').max(200),
  line2: z.string().trim().max(200).optional().default(''),
  city: z.string().trim().min(2, 'Enter the city').max(100),
  state: z.string().trim().max(100).optional().default(''),
  postal_code: z.string().trim().max(20).optional().default(''),
  // Coordinates come from the screen's pin state, not from a registered field.
  site_type: z.enum(['standalone_house', 'apartment', 'basement', 'society', 'commercial']),
  access_notes: z.string().trim().min(5, 'Describe how your partner should reach the car').max(2000),
  parking_details: z.string().trim().max(1000).optional().default(''),
  property_approval: z.boolean().default(false),
});

export type AddressValues = z.input<typeof addressSchema>;

// ------------------------------------------------------------------- offers

export const offerResponseSchema = z.object({
  reason_code: z.enum([
    'too_far',
    'no_capacity',
    'not_qualified',
    'site_not_suitable',
    'equipment',
    'other',
  ]),
});

// --------------------------------------------------------------- reporting

const REPORT_CATEGORY_VALUES = [
  'issue',
  'damage',
  'unsafe_site',
  'emergency',
  'payment',
  'no_show',
  'other',
] as const;

export type ReportCategory = (typeof REPORT_CATEGORY_VALUES)[number];

export const reportSchema = z.object({
  category: z.enum(REPORT_CATEGORY_VALUES),
  description: z.string().trim().min(10, 'Describe what happened').max(4000),
});

/**
 * Picker options, typed against the validated enum.
 *
 * The API rejects any category outside this set, so the list is declared next to the
 * schema and typed from it: a screen cannot offer a value the server will refuse, and
 * a new backend category fails to compile here instead of 400ing in the field.
 */
export const reportCategoryOptions: { value: ReportCategory; label: string }[] = [
  { value: 'issue', label: 'Service issue' },
  { value: 'damage', label: 'Damage' },
  { value: 'unsafe_site', label: 'Unsafe site' },
  { value: 'emergency', label: 'Emergency' },
  { value: 'payment', label: 'Payment problem' },
  { value: 'no_show', label: 'Partner no-show' },
  { value: 'other', label: 'Something else' },
];

export const ratingSchema = z.object({
  rating: z.number().int().min(1, 'Choose a rating').max(5),
  comment: z.string().trim().max(2000).optional().default(''),
});

// -------------------------------------------------------------- chat message

export const chatMessageSchema = z.object({
  body: z.string().trim().min(1, 'Type a message').max(2000),
});

// ------------------------------------------------------------------ checklist

export const checklistUpdateSchema = z.object({
  items: z.array(
    z.object({
      code: z.string(),
      done: z.boolean(),
    }),
  ),
});

// ---------------------------------------------------------- evidence checks

/**
 * Guided capture checks.
 *
 * Every field must be explicitly answered true or false. The server refuses a
 * guided capture with missing checks, so this matches that contract exactly.
 */
export const guidedChecksSchema = z.object({
  lighting_ok: z.boolean(),
  angle_ok: z.boolean(),
  identity_confirmed: z.boolean(),
});
