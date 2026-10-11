/**
 * Typed endpoint functions, one per API use case.
 *
 * Screens call these; they never build URLs or touch `apiClient` directly. Keeping
 * the mapping in one place is what makes the API surface reviewable and keeps the
 * contract in `types.ts` honest.
 */

import { apiClient } from './client';
import type {
  Address,
  AuthSession,
  Booking,
  BookingEvent,
  BookingSummary,
  ChatMessage,
  ChatThread,
  ChecklistItem,
  DispatchOffer,
  EarningsSummary,
  Evidence,
  MeResponse,
  NotificationFeed,
  NotificationPreferences,
  Paginated,
  PartnerDocument,
  PartnerEquipmentItem,
  PartnerJob,
  PartnerMeResponse,
  PartnerPayable,
  PartnerProfile,
  PartnerSkill,
  PriceRuleVersion,
  Quote,
  ReconciliationItem,
  ServiceDetail,
  ServiceType,
  ServiceZone,
  AddOn,
  SupportCase,
  TransitionInfo,
  Vehicle,
  ZoneAvailability,
  PilotDashboard,
  OpsException,
  PayoutBatch,
  PaymentAttempt,
  PaymentMethod,
} from './types';

// ---------------------------------------------------------------- identity

export const authApi = {
  requestOtp: (phone: string, purpose: 'login' | 'register' = 'login') =>
    apiClient.post<{
      challenge_id: string;
      expires_at: number;
      retry_after_seconds: number;
      attempts_remaining: number;
      locked: boolean;
      expired: boolean;
    }>('/auth/otp/request', { phone, purpose }),

  verifyOtp: (challengeId: string, code: string) =>
    apiClient.post<AuthSession>('/auth/otp/verify', { challenge_id: challengeId, code }),

  resendOtp: (challengeId: string) =>
    apiClient.post<{ challenge_id: string; retry_after_seconds: number }>('/auth/otp/resend', {
      challenge_id: challengeId,
    }),

  // `authenticated: false` is essential on the token endpoints. Without it a 401 from
  // /auth/refresh re-enters the refresh path, and because the refresh handler is
  // single-flight it hands back the very promise that is awaiting this call: the two
  // await each other forever and the app never leaves its "restoring session" splash.
  refresh: (refreshToken: string) =>
    apiClient.post<AuthSession>(
      '/auth/refresh',
      { refresh_token: refreshToken },
      { authenticated: false, noRetry: true },
    ),

  logout: (refreshToken?: string) =>
    apiClient.post<void>(
      '/auth/logout',
      { refresh_token: refreshToken ?? '' },
      { authenticated: false, noRetry: true },
    ),

  registerCustomer: (payload: Record<string, unknown>) =>
    apiClient.post<{ user_id: string; address: Address; vehicle: Vehicle; consent_version: string }>(
      '/auth/register/customer',
      payload,
    ),

  registerPartner: (payload: Record<string, unknown>) =>
    apiClient.post<{ user_id: string; partner: PartnerProfile; next: string }>(
      '/auth/register/partner',
      payload,
    ),
};

export const meApi = {
  get: () => apiClient.get<MeResponse>('/me'),

  update: (payload: { full_name?: string; email?: string }) =>
    apiClient.patch<MeResponse>('/me', payload),

  getPreferences: () => apiClient.get<NotificationPreferences>('/me/preferences'),

  updatePreferences: (payload: Partial<NotificationPreferences>) =>
    apiClient.patch<NotificationPreferences>('/me/preferences', payload),

  getConsents: () => apiClient.get<{ consent_type: string; granted: boolean; version: string }[]>('/me/consents'),

  submitDataRequest: (kind: 'export' | 'delete') =>
    apiClient.post<{ request_id: string; status: string; note: string }>('/me/data-requests', { kind }),

  registerDevice: (token: string, platform: 'ios' | 'android') =>
    apiClient.post<{ id: string }>('/devices', { token, platform }),

  removeDevice: (token: string) => apiClient.delete<void>('/devices', { query: { token } }),
};

// ------------------------------------------------------------------ garage

export const vehicleApi = {
  list: () => apiClient.get<Vehicle[]>('/vehicles'),
  create: (payload: Partial<Vehicle>) => apiClient.post<Vehicle>('/vehicles', payload),
  update: (id: string, payload: Partial<Vehicle>) => apiClient.patch<Vehicle>(`/vehicles/${id}`, payload),
  remove: (id: string) => apiClient.delete<void>(`/vehicles/${id}`),
};

export const addressApi = {
  list: () => apiClient.get<Address[]>('/addresses'),
  create: (payload: Record<string, unknown>) => apiClient.post<Address>('/addresses', payload),
  update: (id: string, payload: Record<string, unknown>) =>
    apiClient.patch<Address>(`/addresses/${id}`, payload),
  remove: (id: string) => apiClient.delete<void>(`/addresses/${id}`),
};

// ----------------------------------------------------------------- catalog

export const catalogApi = {
  services: (params: { site_type?: string; vehicle_type?: string } = {}) =>
    apiClient.get<ServiceType[]>('/catalog/services', { query: params }),

  service: (code: string) => apiClient.get<ServiceDetail>(`/catalog/services/${code}`),

  addons: (serviceCode?: string) =>
    apiClient.get<AddOn[]>('/catalog/addons', { query: { service_code: serviceCode } }),

  currentPriceRule: () =>
    apiClient.get<{ results: PriceRuleVersion[] }>('/quotes/price-rules').then((r) => r.results[0] ?? null),
};

export const zoneApi = {
  list: (params: { city?: string; lat?: number; lng?: number } = {}) =>
    apiClient.get<ServiceZone[]>('/zones', { query: params }),

  availability: (code: string, date?: string) =>
    apiClient.get<ZoneAvailability>(`/zones-availability/${code}`, { query: { date } }),
};

// ------------------------------------------------------------------ quotes

export interface QuoteRequest {
  vehicle_id: string;
  address_id: string;
  service_code: string;
  addon_codes?: string[];
  booking_mode: 'scheduled' | 'on_demand';
  window_start?: string | null;
  window_end?: string | null;
  coupon_code?: string;
}

export const quoteApi = {
  create: (payload: QuoteRequest) => apiClient.post<Quote>('/quotes', payload),

  get: (id: string) => apiClient.get<Quote>(`/quotes/${id}`),

  accept: (id: string, termsVersion: string) =>
    apiClient.post<Quote>(`/quotes/${id}`, { action: 'accept', terms_version: termsVersion }),

  decline: (id: string) => apiClient.post<Quote>(`/quotes/${id}`, { action: 'decline' }),
};

// ---------------------------------------------------------------- bookings

export interface BookingFilters {
  status?: string;
  booking_mode?: string;
  zone?: string;
  active?: boolean;
  from?: string;
  to?: string;
  page?: number;
  page_size?: number;
}

export const bookingApi = {
  list: (filters: BookingFilters = {}) =>
    apiClient.get<Paginated<BookingSummary>>('/bookings', { query: filters as Record<string, string | number | boolean | undefined> }),

  get: (reference: string) => apiClient.get<Booking>(`/bookings/${reference}`),

  events: (reference: string) => apiClient.get<BookingEvent[]>(`/bookings/${reference}/events`),

  transitions: (reference: string) => apiClient.get<TransitionInfo>(`/bookings/${reference}/transitions`),

  create: (quoteId: string, noContact = false) =>
    apiClient.post<Booking>(
      '/bookings',
      {
        quote_id: quoteId,
        terms_accepted: true,
        cancellation_policy_accepted: true,
        no_contact: noContact,
      },
      { idempotencyKey: apiClient.newIdempotencyKey() },
    ),

  cancel: (reference: string, reasonCode: string, reasonText = '') =>
    apiClient.post<{ booking: Booking; cancellation: Record<string, unknown> }>(
      `/bookings/${reference}/cancel`,
      { reason_code: reasonCode, reason_text: reasonText },
      { idempotencyKey: apiClient.newIdempotencyKey() },
    ),

  rate: (reference: string, rating: number, comment = '') =>
    apiClient.post<Booking>(`/bookings/${reference}/rating`, { rating, comment }),

  milestone: (reference: string, milestone: 'en_route' | 'arrived' | 'start', payload: Record<string, unknown> = {}) =>
    apiClient.post<Booking>(`/bookings/${reference}/milestones/${milestone}`, payload),

  complete: (reference: string, notes = '') =>
    apiClient.post<Booking>(
      `/bookings/${reference}/complete`,
      { checklist_confirmed: true, notes },
      { idempotencyKey: apiClient.newIdempotencyKey() },
    ),

  checklist: (reference: string) => apiClient.get<ChecklistItem[]>(`/bookings/${reference}/checklist`),

  updateChecklist: (reference: string, items: { code: string; done: boolean }[], allDone = false) =>
    apiClient.post<ChecklistItem[]>(`/bookings/${reference}/checklist`, { items, all_done: allDone }),

  acknowledge: (
    reference: string,
    payload: { kind: string; vehicle_confirmed?: boolean; condition_confirmed?: boolean; notes?: string },
  ) => apiClient.post(`/bookings/${reference}/acknowledge`, payload),

  reportIssue: (
    reference: string,
    payload: { category: string; description: string; evidence_ids?: string[] },
  ) => apiClient.post<SupportCase>(`/bookings/${reference}/issue`, payload),
};

// ---------------------------------------------------------------- evidence

export interface EvidenceUpload {
  evidence_type: 'pre_condition' | 'post_service' | 'damage' | 'other';
  captured_at: string;
  client_photo_id: string;
  sequence: number;
  checks: Record<string, boolean>;
  file: { uri: string; name: string; type: string };
}

export const evidenceApi = {
  list: (reference: string) => apiClient.get<Evidence[]>(`/bookings/${reference}/evidence/list`),

  upload: (reference: string, upload: EvidenceUpload) => {
    const form = new FormData();
    form.append('evidence_type', upload.evidence_type);
    form.append('captured_at', upload.captured_at);
    form.append('client_photo_id', upload.client_photo_id);
    form.append('sequence', String(upload.sequence));
    // Sent as JSON text: multipart fields arrive as strings, and the server
    // decodes this with a JSONField.
    form.append('checks', JSON.stringify(upload.checks));
    form.append('file', {
      uri: upload.file.uri,
      name: upload.file.name,
      type: upload.file.type,
    } as unknown as Blob);
    return apiClient.upload<Evidence>(`/bookings/${reference}/evidence`, form);
  },
};

// ---------------------------------------------------------------- payments

export const paymentApi = {
  methods: () => apiClient.get<PaymentMethod[]>('/payments/methods'),

  addMethod: (payload: {
    provider_token: string;
    brand?: string;
    last4?: string;
    expiry_month?: number;
    expiry_year?: number;
  }) => apiClient.post<PaymentMethod>('/payments/methods', payload),

  removeMethod: (id: string) => apiClient.delete<void>(`/payments/methods/${id}`),

  /** Authorising is a money command, so it carries an idempotency key. */
  authorize: (bookingReference: string, paymentMethodId: string) =>
    apiClient.post<PaymentAttempt>(
      '/payments/authorizations',
      { booking_reference: bookingReference, payment_method_id: paymentMethodId },
      { idempotencyKey: apiClient.newIdempotencyKey() },
    ),

  /** Unified post-wash checkout: authorize + capture with an idempotency key. */
  pay: (
    bookingReference: string,
    payload: { payment_method_kind: string; amount_minor: number; currency: string },
  ) =>
    apiClient.post<PaymentAttempt>(
      `/bookings/${bookingReference}/pay`,
      payload,
      { idempotencyKey: apiClient.newIdempotencyKey() },
    ),

  forBooking: (reference: string) =>
    apiClient.get<{
      booking_reference: string;
      currency: string;
      total_minor: number;
      captured_minor: number;
      refunded_minor: number;
      attempts: PaymentAttempt[];
      refunds: unknown[];
      ledger: unknown[];
      payable: PartnerPayable | null;
    }>(`/bookings/${reference}/payments`),
};

// ---------------------------------------------------------------- partners

export const partnerApi = {
  me: () => apiClient.get<PartnerMeResponse>('/partners/me'),

  updateProfile: (payload: Record<string, unknown>) => apiClient.patch<PartnerProfile>('/partners/me', payload),

  setAvailability: (payload: {
    action: 'start' | 'end';
    starts_at?: string;
    ends_at?: string;
    zone_code?: string;
    declared_capacity_minutes?: number;
    service_radius_km?: number;
    default_capacity?: number;
  }) => apiClient.put<{ shift: unknown; location_sharing_active: boolean }>('/partners/me/availability', payload),

  sendLocation: (payload: {
    latitude: number;
    longitude: number;
    accuracy_m?: number | null;
    recorded_at: string;
  }) =>
    apiClient.post<{ accepted: boolean; recorded_at: string }>('/partners/me/location', payload, {
      noRetry: true,
    }),

  skills: () => apiClient.get<PartnerSkill[]>('/partners/me/skills'),

  setSkills: (skills: { service_code: string; proficiency: string }[]) =>
    apiClient.put<PartnerSkill[]>('/partners/me/skills', { skills }),

  equipment: () => apiClient.get<PartnerEquipmentItem[]>('/partners/me/equipment'),

  setEquipment: (items: { item_code: string; status: string; notes?: string }[]) =>
    apiClient.put<{ items: PartnerEquipmentItem[]; readiness: unknown }>('/partners/me/equipment', { items }),

  documents: () => apiClient.get<PartnerDocument[]>('/partners/me/documents'),

  uploadDocument: (form: FormData) => apiClient.upload<PartnerDocument>('/partners/me/documents', form),

  earnings: (params: { from?: string; to?: string } = {}) =>
    apiClient.get<EarningsSummary>('/partners/me/earnings', { query: params }),

  declareUnavailability: (payload: {
    starts_at: string;
    ends_at: string;
    reason_code: string;
    reason_text?: string;
  }) => apiClient.post('/partners/me/unavailability', payload),
};

// ---------------------------------------------------------------- dispatch

export const dispatchApi = {
  offers: (includeExpired = false) =>
    apiClient.get<{ results: DispatchOffer[]; count: number }>('/dispatch/offers', {
      query: { include_expired: includeExpired },
    }),

  offer: (id: string) => apiClient.get<DispatchOffer>(`/dispatch/offers/${id}`),

  accept: (id: string) =>
    apiClient.post<{ booking: Booking }>(
      `/dispatch/offers/${id}`,
      { action: 'accept' },
      { idempotencyKey: apiClient.newIdempotencyKey() },
    ),

  decline: (id: string, reasonCode = 'other') =>
    apiClient.post<{ status: string }>(`/dispatch/offers/${id}`, { action: 'decline', reason_code: reasonCode }),

  job: (reference: string) => apiClient.get<PartnerJob>(`/bookings/${reference}/job`),
};

// ------------------------------------------------------------------- comms

export const commsApi = {
  threads: () => apiClient.get<ChatThread[]>('/comms/threads'),

  messages: (reference: string) =>
    apiClient.get<ChatMessage[]>(`/comms/threads/${reference}/messages`),

  send: (reference: string, body: string) =>
    apiClient.post<ChatMessage>(`/comms/threads/${reference}/messages`, { body }),

  startCall: (reference: string) =>
    apiClient.post<{ call_id: string; masked_number: string; note: string }>(
      `/comms/threads/${reference}/call`,
      {},
    ),
};

// ----------------------------------------------------------- notifications

export const notificationApi = {
  list: (params: { unread_only?: boolean; limit?: number } = {}) =>
    apiClient.get<NotificationFeed>('/notifications', { query: params }),

  markRead: (id: string) => apiClient.patch(`/notifications/${id}/read`),

  markAllRead: () => apiClient.post<{ updated: number }>('/notifications/read-all'),
};

// ----------------------------------------------------------------- support

export const supportApi = {
  list: () => apiClient.get<SupportCase[]>('/support/cases'),

  get: (reference: string) => apiClient.get<SupportCase>(`/support/cases/${reference}`),

  addNote: (reference: string, body: string) =>
    apiClient.post(`/support/cases/${reference}/notes`, { body }),
};

// --------------------------------------------------------------------- ops

export const opsApi = {
  jobs: (params: Record<string, string | number | boolean | undefined> = {}) =>
    apiClient.get<BookingSummary[]>('/ops/jobs', { query: params }),

  job: (reference: string) => apiClient.get<Booking & Record<string, unknown>>(`/ops/jobs/${reference}`),

  exceptions: (type?: string) =>
    apiClient.get<{ results: OpsException[]; count: number }>('/ops/exceptions', { query: { type } }),

  assign: (reference: string, partnerId: string, reason: string) =>
    apiClient.post<Booking>(`/ops/jobs/${reference}/assign`, { partner_id: partnerId, reason }),

  override: (reference: string, toStatus: string, reason: string) =>
    apiClient.post<{ booking: Booking; audit_id: string }>(`/ops/jobs/${reference}/override`, {
      to_status: toStatus,
      reason,
    }),

  partners: (params: { status?: string; expiring?: boolean } = {}) =>
    apiClient.get<PartnerProfile[]>('/ops/partners', { query: params }),

  decidePartner: (partnerId: string, action: 'approve' | 'suspend' | 'reinstate', reason = '') =>
    apiClient.post<{ partner: PartnerProfile; audit_id: string }>(
      `/ops/partners/${partnerId}/${action}`,
      { reason },
    ),

  zones: () => apiClient.get<ServiceZone[]>('/ops/zones'),

  pauseZone: (zoneId: string, reason: string, resume = false) =>
    apiClient.post<ServiceZone>(`/ops/zones/${zoneId}/pause`, { reason, resume }),

  cases: (params: Record<string, string | undefined> = {}) =>
    apiClient.get<SupportCase[]>('/ops/support-cases', { query: params }),

  updateCase: (reference: string, payload: Record<string, unknown>) =>
    apiClient.post<SupportCase>(`/ops/support-cases/${reference}`, payload),

  refunds: () => apiClient.get<unknown[]>('/ops/refunds'),

  reconciliation: (params: { status?: string; kind?: string } = {}) =>
    apiClient.get<ReconciliationItem[]>('/ops/reconciliation', { query: params }),

  runReconciliation: (runDate?: string) =>
    apiClient.post<Record<string, number | string>>('/ops/reconciliation', { run_date: runDate }),

  dashboard: (params: { zone?: string; group_by?: string } = {}) =>
    apiClient.get<PilotDashboard>('/ops/dashboards/pilot', { query: params }),

  payouts: () => apiClient.get<PayoutBatch[]>('/ops/payouts'),

  approvePayout: (reference: string) =>
    apiClient.post<PayoutBatch>(`/ops/payouts/${reference}/approve`),

  payPayout: (reference: string) => apiClient.post<PayoutBatch>(`/ops/payouts/${reference}/pay`),

  audit: (params: Record<string, string | undefined> = {}) =>
    apiClient.get<
      {
        id: string;
        action: string;
        target_type: string;
        target_id: string;
        reason: string;
        actor: string;
        actor_role: string;
        created_at: string;
      }[]
    >('/ops/audit', { query: params }),
};
