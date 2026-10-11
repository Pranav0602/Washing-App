/**
 * API data types.
 *
 * These mirror the Django REST serializers exactly. Field names are snake_case
 * because they come straight off the wire: renaming them in the client would be
 * duplicated truth for no benefit, and `format.ts` handles presentation instead.
 */

export type Role = 'customer' | 'partner' | 'ops' | 'admin';

export type BookingStatus =
  | 'requested'
  | 'quote_accepted'
  | 'dispatching'
  | 'assigned'
  | 'en_route'
  | 'arrived'
  | 'in_service'
  | 'completed'
  | 'payment_captured'
  | 'partner_payout_eligible'
  | 'expired_offer'
  | 'no_partner_available'
  | 'cancelled'
  | 'partner_no_show'
  | 'unsafe_site'
  | 'payment_failed'
  | 'disputed_work'
  | 'refunded';

export type SiteType =
  | 'standalone_house'
  | 'apartment'
  | 'basement'
  | 'society'
  | 'commercial';

export type VehicleType = 'car' | 'suv' | 'truck' | 'van' | 'bike' | 'scooter';
export type SizeTier = 'S' | 'M' | 'L' | 'H';
export type BookingMode = 'scheduled' | 'on_demand';

export type EvidenceType = 'pre_condition' | 'post_service' | 'damage' | 'other';

// ---------------------------------------------------------------- identity

export interface User {
  id: string;
  phone: string;
  email: string;
  full_name: string;
  roles: Role[];
  account_complete: boolean;
  partner_status: PartnerStatus | null;
}

export interface RoleGrant {
  id: string;
  role: Role;
  granted_at: string;
  revoked_at: string | null;
}

export interface NotificationPreferences {
  push_enabled: boolean;
  email_enabled: boolean;
  sms_enabled: boolean;
  booking_updates: boolean;
  assignment_alerts: boolean;
  offer_alerts: boolean;
  marketing: boolean;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
}

export interface MeResponse extends User {
  roles_detail: RoleGrant[];
  notification_preferences: NotificationPreferences;
}

export interface AuthSession {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  access_expires_at: string;
  refresh_expires_at: string;
  user: User;
  /** Which screen the app should route to next. */
  next: 'complete_profile' | 'register_customer' | 'register_partner' | 'customer_home' | 'partner_home' | 'ops_home';
}

// --------------------------------------------------------------- customers

export interface Vehicle {
  id: string;
  vehicle_type: VehicleType;
  vehicle_type_label: string;
  make: string;
  model: string;
  year: number | null;
  color: string;
  registration_number: string;
  license_plate: string;
  size_tier: SizeTier;
  size_tier_label: string;
  display_name: string;
  is_default: boolean;
  is_active: boolean;
  created_at: string;
}

export interface Address {
  id: string;
  label: string;
  line1: string;
  line2: string;
  city: string;
  state: string;
  postal_code: string;
  country: string;
  latitude: number;
  longitude: number;
  site_type: SiteType;
  site_type_label: string;
  access_notes: string;
  parking_details: string;
  property_approval: boolean;
  is_default: boolean;
  summary: string;
  created_at: string;
}

// ----------------------------------------------------------------- catalog

export interface ServiceType {
  code: string;
  name: string;
  description: string;
  base_price_minor: number;
  currency: string;
  currency_display: { minor_unit: string; amount_minor: number };
  expected_duration_minutes: number;
  allowed_site_types: SiteType[];
  allowed_vehicle_tiers: SizeTier[];
  requires_water_source: boolean;
  requires_power_source: boolean;
  inclusions: string[];
  exclusions: string[];
}

export interface ServiceDetail extends ServiceType {
  addons: AddOn[];
}

export interface AddOn {
  code: string;
  name: string;
  description: string;
  price_minor: number;
  currency: string;
  duration_delta_minutes: number;
  allowed_service_codes: string[];
  allowed_site_types: SiteType[];
}

export interface PriceRuleVersion {
  id: string;
  version: string;
  display_name: string;
  currency: string;
  tax_bps: number;
  platform_fee_minor: number;
}

// ------------------------------------------------------------------- zones

export interface ZoneServiceWindow {
  id: number;
  weekday: number;
  opens_at_minutes: number;
  closes_at_minutes: number;
  allows_scheduled: boolean;
  allows_on_demand: boolean;
  max_jobs: number;
}

export interface ServiceZone {
  id: string;
  code: string;
  name: string;
  city: string;
  timezone_name: string;
  is_active: boolean;
  is_paused: boolean;
  pause_reason: string;
  max_concurrent_jobs: number;
  booking_cap_per_day: number;
  on_demand_enabled: boolean;
  on_demand_radius_km: number;
  service_windows: ZoneServiceWindow[];
  is_bookable: boolean;
}

export interface ZoneSlot {
  id: string;
  starts_at: string;
  ends_at: string;
  capacity: number;
  booked_count: number;
  remaining: number;
  is_full: boolean;
  allows_on_demand: boolean;
}

export interface ZoneAvailability {
  zone: string;
  windows: ZoneServiceWindow[];
  slots: ZoneSlot[];
  on_demand_available: boolean;
  capacity_remaining: number;
}

// ------------------------------------------------------------------ quotes

export type QuoteLineType =
  | 'service_base'
  | 'vehicle_tier'
  | 'addon'
  | 'zone_travel'
  | 'tax'
  | 'fee'
  | 'discount';

export interface QuoteLine {
  id: string;
  line_type: QuoteLineType;
  line_type_label: string;
  ref_code: string;
  description: string;
  quantity: number;
  unit_price_minor: number;
  amount_minor: number;
  sort_order: number;
  meta: Record<string, unknown>;
}

export interface Quote {
  id: string;
  service_name: string;
  service_code: string;
  vehicle_name: string;
  zone_code: string;
  booking_mode: BookingMode;
  window_start: string | null;
  window_end: string | null;
  status: 'draft' | 'quoted' | 'accepted' | 'locked' | 'declined' | 'expired' | 'superseded';
  is_expired: boolean;
  currency: string;
  subtotal_minor: number;
  tax_minor: number;
  fee_minor: number;
  discount_minor: number;
  total_minor: number;
  price_rule_version_label: string;
  expected_duration_minutes: number;
  distance_km: number | null;
  inclusions: string[];
  exclusions: string[];
  lines: QuoteLine[];
  expires_at: string;
  accepted_at: string | null;
  created_at: string;
}

// ---------------------------------------------------------------- bookings

export interface BookingSummary {
  id: string;
  reference: string;
  status: BookingStatus;
  status_label: string;
  service_name: string;
  vehicle_name: string;
  zone_code: string;
  partner_name: string | null;
  booking_mode: BookingMode;
  currency: string;
  total_minor: number;
  window_start: string | null;
  window_end: string | null;
  scheduled_start: string | null;
  promise_window_start: string | null;
  promise_window_end: string | null;
  created_at: string;
}

export interface BookingAddress {
  line1: string;
  line2: string;
  city: string;
  postal_code: string;
  latitude: number;
  longitude: number;
  site_type: SiteType;
  access_notes: string;
  parking_details: string;
}

export interface BookingPartner {
  id: string;
  display_name: string;
  rating_avg: number;
  rating_count: number;
  masked_phone: string;
}

export interface ChecklistItem {
  id: string;
  code: string;
  label: string;
  is_required: boolean;
  is_done: boolean;
  done_at: string | null;
  notes: string;
  sort_order: number;
}

export interface AllowedTransition {
  action: string;
  to_status: BookingStatus;
  description: string;
  requires_reason: boolean;
  guards: string[];
}

export interface Booking extends BookingSummary {
  subtotal_minor: number;
  tax_minor: number;
  fee_minor: number;
  discount_minor: number;
  captured_minor: number;
  refunded_minor: number;
  payment_state: string;
  payment_state_label: string;
  authorized_minor: number;
  expected_duration_minutes: number;
  eta_seconds_at_assignment: number | null;
  assigned_at: string | null;
  en_route_at: string | null;
  arrived_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  cancel_reason: string;
  reassign_count: number;
  terms_accepted_at: string | null;
  terms_version: string;
  cancellation_policy_snapshot: Record<string, number | string>;
  no_contact: boolean;
  rating: number | null;
  rating_comment: string;
  booking_code: string;
  address: BookingAddress;
  vehicle: { id: string; display_name: string; vehicle_type: VehicleType; make: string; model: string; color: string; registration_number: string };
  partner: BookingPartner | null;
  checklist: ChecklistItem[];
  evidence_summary: { pre_condition: number; post_service: number; total: number };
  allowed_transitions: AllowedTransition[];
  can_cancel: boolean;
  is_arrival_late: boolean;
}

export interface BookingEvent {
  seq: number;
  event_type: string;
  from_status: string;
  to_status: string;
  actor_type: string;
  actor_role: string;
  reason: string;
  metadata: Record<string, unknown>;
  occurred_at: string;
}

export interface TransitionInfo {
  reference: string;
  current: BookingStatus;
  role: string;
  is_terminal: boolean;
  allowed: AllowedTransition[];
}

export interface Paginated<T> {
  count: number;
  page: number;
  page_size: number;
  total_pages: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

// ---------------------------------------------------------------- evidence

export interface Evidence {
  id: string;
  booking_id: string;
  evidence_type: EvidenceType;
  evidence_type_label: string;
  sequence: number;
  captured_at: string;
  uploaded_at: string | null;
  upload_status: string;
  content_type: string;
  byte_size: number;
  checks: Record<string, boolean>;
  access_policy: string;
  retention_deadline: string;
  legal_hold: boolean;
  is_available: boolean;
  file_url: string | null;
  created_at: string;
}

// ---------------------------------------------------------------- payments

export interface PaymentMethod {
  id: string;
  provider: string;
  brand: string;
  last4: string;
  expiry_month: number | null;
  expiry_year: number | null;
  is_default: boolean;
  display_label: string;
  created_at: string;
}

export interface PaymentAttempt {
  id: string;
  booking_id: string;
  attempt_type: string;
  status: string;
  amount_minor: number;
  captured_minor: number;
  currency: string;
  provider: string;
  failure_code: string;
  failure_message: string;
  authorized_at: string | null;
  captured_at: string | null;
  created_at: string;
}

// ---------------------------------------------------------------- partners

export type PartnerStatus = 'draft' | 'pending_verification' | 'approved' | 'suspended' | 'rejected';

export interface ReadinessBlocker {
  code: string;
  message: string;
  detail: string;
}

export interface Readiness {
  eligible_for_offers: boolean;
  summary: string;
  blockers: ReadinessBlocker[];
}

export interface PartnerProfile {
  id: string;
  display_name: string;
  bio: string;
  status: PartnerStatus;
  status_label: string;
  masked_phone: string;
  payout_provider: string;
  commission_bps: number;
  service_radius_km: number;
  default_capacity: number;
  home_zone_id: string | null;
  rating_avg: number;
  rating_count: number;
  insurance_expires_at: string | null;
  certification_expires_at: string | null;
  assessment_passed_at: string | null;
  suspension_reason: string;
  last_location_at: string | null;
  readiness: Readiness;
  created_at: string;
}

export interface PartnerMeResponse extends PartnerProfile {
  location: {
    has_location: boolean;
    last_recorded_at: string | null;
    age_seconds: number | null;
    is_stale: boolean;
    latitude?: number | null;
    longitude?: number | null;
  };
  active_shift: PartnerShift | null;
}

export interface PartnerShift {
  id: string;
  zone_code: string | null;
  starts_at: string;
  ends_at: string;
  declared_capacity_minutes: number;
  status: 'planned' | 'active' | 'ended' | 'cancelled';
  is_current: boolean;
}

export interface PartnerSkill {
  id: string;
  service_code: string;
  service_name: string;
  proficiency: 'trained' | 'assessed' | 'expert';
  certified_at: string | null;
  expires_at: string | null;
  is_current: boolean;
}

export interface PartnerEquipmentItem {
  id: string;
  item_code: string;
  name: string;
  required: boolean;
  status: 'present' | 'missing' | 'expired';
  expires_at: string | null;
  checked_at: string | null;
  notes: string;
  is_satisfied: boolean;
}

export interface PartnerDocument {
  id: string;
  doc_type: string;
  doc_type_label: string;
  content_type: string;
  byte_size: number;
  issued_at: string | null;
  expires_at: string | null;
  verification_status: 'pending' | 'verified' | 'rejected';
  is_expired: boolean;
  file_url: string | null;
  created_at: string;
}

export interface EarningsSummary {
  currency: string;
  summary: {
    gross_minor: number;
    commission_minor: number;
    adjustment_minor: number;
    net_minor: number;
  };
  payables: PartnerPayable[];
  payout_batches: PayoutBatch[];
}

export interface PartnerPayable {
  id: string;
  booking_id: string;
  booking_reference: string;
  partner_id: string;
  gross_minor: number;
  commission_minor: number;
  adjustment_minor: number;
  net_minor: number;
  currency: string;
  status: 'accruing' | 'eligible' | 'scheduled' | 'paid' | 'on_hold' | 'reversed';
  status_label: string;
  eligible_at: string | null;
  hold_reason: string;
  payout_batch_reference: string | null;
}

export interface PayoutBatch {
  id: string;
  reference: string;
  period_start: string;
  period_end: string;
  status: string;
  total_minor: number;
  currency: string;
  partner_count: number;
  payable_count: number;
  paid_at: string | null;
}

// ---------------------------------------------------------------- dispatch

export interface DispatchOffer {
  id: string;
  booking_reference: string;
  status: 'pending' | 'accepted' | 'declined' | 'expired' | 'superseded' | 'withdrawn';
  expires_at: string;
  seconds_remaining: number;
  dispatch_round: number;
  rank: number;
  payout_estimate_minor: number;
  currency: string;
  eta_seconds: number | null;
  eta_is_estimate: boolean;
  distance_km: number | null;
  service: { code: string; name: string };
  vehicle: { display_name: string; make: string; model: string; color: string; size_tier: SizeTier };
  location: { line1: string; line2: string; city: string; latitude: number; longitude: number; site_type: SiteType };
  access_notes: string;
  expected_duration_minutes: number;
  window_start: string | null;
  is_actionable: boolean;
}

export interface PartnerJob {
  booking: Booking;
  checklist: ChecklistItem[];
  evidence: Evidence[];
  required_evidence: Record<string, string[]>;
  allowed_transitions: AllowedTransition[];
  navigation: { latitude: number; longitude: number; address_lines: string };
  customer_contact: { masked_phone: string; note: string };
}

// -------------------------------------------------------------------- comms

export interface ChatThread {
  id: string;
  booking_reference: string;
  partner_display_name: string | null;
  masked_counterparty_number: string | null;
  status: 'open' | 'closed' | 'expired';
  is_open: boolean;
  opened_at: string;
  closes_at: string;
  closed_at: string | null;
  last_message_at: string | null;
}

export interface ChatMessage {
  id: string;
  sender: string;
  sender_role: 'customer' | 'partner';
  is_mine: boolean;
  body: string;
  created_at: string;
  read_at: string | null;
}

// ----------------------------------------------------------- notifications

export interface AppNotification {
  id: string;
  kind: string;
  kind_label: string;
  title: string;
  body: string;
  data: Record<string, unknown>;
  booking_id: string | null;
  read_at: string | null;
  is_read: boolean;
  created_at: string;
}

export interface NotificationFeed {
  count: number;
  unread_count: number;
  results: AppNotification[];
}

// ----------------------------------------------------------------- support

export interface SupportCase {
  id: string;
  reference: string;
  booking_reference: string | null;
  category: string;
  category_label: string;
  priority: 'low' | 'normal' | 'high' | 'critical';
  priority_label: string;
  status: string;
  status_label: string;
  subject: string;
  description: string;
  evidence_frozen: boolean;
  sla_due_at: string | null;
  first_response_at: string | null;
  is_sla_breached: boolean;
  escalation_target: string;
  resolution: string;
  liability_outcome: string;
  liability_notes: string;
  created_at: string;
  resolved_at: string | null;
  notes: { id: string; body: string; created_at: string }[];
}

// --------------------------------------------------------------------- ops

export interface OpsException {
  reference: string;
  booking_id: string;
  type: string;
  severity: 'low' | 'medium' | 'high';
  age_seconds: number;
  status: BookingStatus;
  zone: string;
  partner: string | null;
  detail: Record<string, unknown>;
}

export interface DashboardMetric {
  name: string;
  definition: string;
  value: number | null;
  ratio: number | null;
  numerator: number;
  denominator: number;
  unit: string;
  target?: number;
  note: string;
  distribution?: Record<string, number>;
}

export interface PilotDashboard {
  zone: string | null;
  period_start: string;
  period_end: string;
  currency: string;
  metrics: DashboardMetric[];
  contribution_per_wash_minor: number | null;
  warnings: string[];
}

export interface ReconciliationItem {
  id: string;
  run_date: string;
  provider: string;
  provider_event_id: string;
  kind: string;
  status: string;
  status_label: string;
  booking_reference: string | null;
  expected_minor: number;
  actual_minor: number;
  difference_minor: number;
  currency: string;
  notes: string;
  resolved_at: string | null;
}
