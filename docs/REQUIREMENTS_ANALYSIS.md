# Phase 1 — Requirements Analysis

Source of truth: `Car Wash Platform - Improved Implementation Plan.pdf` (v2.0, Decision Draft, 1 Oct 2026, 9 pages).
Extracted verbatim-faithfully. Nothing below is invented; every item traces to a PDF section.
Items marked **[ASSUMPTION]** or **[OPEN]** are not decided by the PDF.

Terminology mapping (PDF → code):

| PDF term | Code term | Notes |
|---|---|---|
| Customer | `customer` | existing scaffold called this "User" |
| Partner | `partner` | existing scaffold called this "Vendor" |
| Operations | `ops` | operations console / dispatcher |
| Admin | `admin` | least-privilege staff superuser |
| Outlet | *out of scope* | PDF defers to "Later" |
| Booking | `Booking` | the job |

---

## A. Application overview

### What it does

An on-demand **doorstep car wash marketplace**. A customer books a wash at a pinned location; the
platform produces a transparent itemised quote, authorises payment, dispatches a nearby vetted
partner (a "washer"), the partner travels to the site, captures guided before/after photo evidence,
completes a checklist, and the platform captures payment, produces a partner payable, and reconciles
against the payment provider.

The PDF's stated product thesis: *"Build a dependable local service marketplace, not a broad
multi-city platform on day one."* The first release must make **the full job loop work**:
`quote → book → match → complete with evidence → charge → pay the partner → resolve exceptions`.

### Target users

1. **Customers** — vehicle owners in 2–3 dense zones of one launch city.
2. **Partners** — independent washers with explicit operating zones, hours, skills, equipment checks.
3. **Operations staff** — dispatchers/support agents who keep the loop operable by hand during the pilot.
4. **Administrators** — staff who approve partners, configure zones/catalog, and perform audited overrides.

### Main workflows

1. **Onboarding & identity** — phone → OTP → role selection → profile completion (customer) or partner application (identity, payout account, documents, kit, training, practical assessment).
2. **Catalogue & quote** — vehicle in garage + service + add-ons + address pin + access notes + time window → itemised quote with expiry.
3. **Booking & authorisation** — accept quote + cancellation terms → authorise payment → booking enters dispatch.
4. **Dispatch & assignment** — eligibility filter → candidate ranking → time-limited offers → atomic first-accept lock → arrival promise.
5. **Fulfilment** — navigate → arrive → verify customer/booking code → pre-service evidence → service → checklist → after evidence → complete.
6. **Money** — capture at completion → partner payable → payout batch → daily provider reconciliation; refunds/partial refunds/chargebacks/failed payout as explicit states.
7. **Exceptions & support** — expired offer, customer cancellation, partner no-show, unsafe site, payment failure, disputed work, refund, reassignment; operator correction requires a recorded reason.
8. **Measurement** — the 8 pilot metrics and the contribution-per-wash formula.

### Main modules

`identity` · `catalog` (vehicles, services, add-ons, price rules) · `zones` (service-zone polygons,
site restrictions) · `quotes` (pricing engine) · `bookings` (state machine + events) · `dispatch`
(eligibility, ranking, offers) · `partners` (profile, skills, equipment, shifts, capacity, readiness) ·
`evidence` (photo records, retention) · `payments` (attempts, ledger, refunds, payables, payouts, reconciliation) ·
`notifications` (outbox, push, in-app) · `comms` (masked phone/chat) · `support` (cases, acknowledgements) ·
`ops` (console API, dashboards, audit) · `common` (base models, permissions, idempotency, errors, outbox).

---

## B. User roles and permissions

Least-privilege is explicit in the PDF (§05 Privacy/security: *"Use least-privilege roles, MFA for staff,
encrypted transport/storage, managed secrets, admin access logs"*). MFA for staff is **[OPEN]** — noted,
implemented as an enforcement point on staff login rather than a full second-factor UX in MVP.

| Role | Permissions | Main capabilities |
|---|---|---|
| **Anonymous** | None | Request OTP, verify OTP, register, read public catalog + active zones, health check |
| **Customer** | Own data only | Manage garage, addresses/pins + access notes, request quotes, accept quotes, book, authorise/cancel own booking, view own booking timeline, view own evidence, masked chat/call for own active booking, report issue/unsafe site/damage, rate completed job, own notification prefs |
| **Partner** | Own profile + **offered** jobs only | Manage availability (shift, radius, capacity), declare skills/equipment, submit location updates **only while on shift or on an active job**, view/accept/decline offers, navigate, mark arrived, verify booking code, upload guided before/after evidence, complete checklist, complete job, view own earnings/payables, raise unsafe-site/damage/emergency report, own notification prefs |
| **Ops** | Zone-scoped job + support read/write | Approve/suspend partners, manage zones + service windows, view live job board + exception queue, **manual assignment**, issue refunds (within approval limit), reassign with reason, manage support cases, view pilot dashboards |
| **Admin** | Global config + audit | All ops powers, plus catalog/price-rule/zone CRUD, partner verification decisions, audit log access, role grants |
| **System/Provider** | Webhook scope only | Payment provider webhooks (signature-verified, idempotent, no user session) |

Explicit negative permissions (PDF-derived):

- A customer **cannot** alter price after acceptance, or jump a booking from `assigned` to paid
  (§04: *"a client must not be able to jump from assigned to paid or alter price after acceptance"*).
- A partner **cannot** see or act on a booking they were not offered, and cannot accept an expired offer.
- A partner's location write is **rejected** unless `on_shift` or `active_job` (§02/§05).
- Nobody but `ops`/`admin` may correct a job, and only with a recorded reason (§01).
- Identity-verification documents are **not** exposed to general support access (§04 Identity).
- Evidence objects are private; access is policy-checked and logged (§04 Evidence).

---

## C. Screen inventory

Roles: **C** = customer, **P** = partner, **O** = ops/admin, **A** = anonymous.
"Existing" = the placeholder screen in `washing-app/screens/` that this replaces.

| Screen | Role | Purpose | Navigation | API dependencies |
|---|---|---|---|---|
| PhoneEntry | A | Enter phone → request OTP | Auth stack, first route | `POST /api/v1/auth/otp/request` |
| OtpVerify | A | Verify OTP → get tokens | Auth stack | `POST /api/v1/auth/otp/verify`, `POST /api/v1/auth/otp/resend` |
| RegisterCustomer | A/C | Complete customer profile + first vehicle | Auth stack → Customer tabs | `POST /api/v1/auth/register/customer` |
| ApplyPartner | A/P | Partner application: identity, payout, documents, skills, equipment | Auth stack → Partner tabs | `POST /api/v1/auth/register/partner`, `POST /api/v1/partners/documents` |
| *(replaces UserTypeSelectionScreen)* | A | Choose Customer or Partner path | Auth stack | — (local only) |
| CustomerHome | C | Next booking, active booking, quick actions | Customer tab 1 | `GET /api/v1/bookings?scope=active`, `GET /api/v1/quotes/...` |
| Garage | C | Vehicle list, add/edit/delete | Customer tab 2 | `GET/POST/PATCH/DELETE /api/v1/vehicles` |
| Addresses | C | Address + map pin + access notes + site type | Customer tab 2 | `GET/POST/PATCH/DELETE /api/v1/addresses` |
| ServiceCatalog | C | Browse services + add-ons by site/vehicle | Stack from Home | `GET /api/v1/catalog/services`, `/addons` |
| QuoteBuilder | C | Pick vehicle/site/add-ons/time window → itemised quote | Stack | `POST /api/v1/quotes` |
| QuoteReview | C | Full total, duration, inclusions/exclusions, expiry, cancellation terms | Stack | `GET /api/v1/quotes/{id}` |
| BookingConfirm | C | Accept terms, authorise payment | Stack | `POST /api/v1/bookings`, `POST /api/v1/payments/authorizations` |
| BookingList | C | All bookings, filters | Customer tab 3 | `GET /api/v1/bookings` |
| BookingDetail (timeline) | C | State timeline, promise window, partner masked contact, evidence | Stack | `GET /api/v1/bookings/{id}`, `/events`, `/evidence` |
| EvidenceViewer | C | Pre/post photos, metadata | Stack | `GET /api/v1/evidence/{id}/file` (signed) |
| JobReport | C | Issue / damage / unsafe-site / emergency report | Modal from BookingDetail | `POST /api/v1/support/cases` |
| Rating | C | Rate completed job | Modal | `POST /api/v1/bookings/{id}/rating` |
| CommsThread | C/P | Masked chat + call relay, active booking only | Modal | `GET/POST /api/v1/comms/threads/{id}/messages`, `POST .../call-token` |
| Notifications | C/P | In-app notification centre | Customer/Partner tab 4 | `GET/PATCH /api/v1/notifications` |
| Profile | C/P | Account, consent, notification prefs, privacy/location disclosure, sign out | Tab | `GET/PATCH /api/v1/me`, `PATCH /api/v1/me/preferences` |
| PartnerHome | P | Shift toggle, live offer feed, earnings snapshot | Partner tab 1 | `GET /api/v1/dispatch/offers`, `GET /api/v1/partners/me/earnings` |
| ShiftAndRadius | P | Set shift, service radius, capacity, availability | Partner tab 2 | `PUT /api/v1/partners/me/availability`, `POST /api/v1/partners/me/location` |
| SkillsAndEquipment | P | Declare skills, kit checklist state | Partner tab 2 | `PUT /api/v1/partners/me/skills`, `/equipment` |
| OfferDetail | P | Payout estimate, vehicle/service, access notes, countdown; accept/decline | Stack | `POST /api/v1/dispatch/offers/{id}/accept`, `/decline` |
| ActiveJob | P | Navigate, mark arrived, code verify, checklist, evidence capture, complete | Stack | `POST /api/v1/bookings/{id}/arrive`, `/start`, `/complete`, evidence endpoints |
| GuidedEvidenceCapture | P | Enforced photo steps: lighting/angle/identity checks | Stack (modal) | `POST /api/v1/bookings/{id}/evidence` |
| Checklist | P | Task checklist incl. included/excluded tasks | Stack | `POST /api/v1/bookings/{id}/checklist` |
| EarningsSummary | P | Payables, payout batches, reconciliation status | Partner tab 3 | `GET /api/v1/partners/me/earnings`, `/payables` |
| PartnerProfile | P | Verification status, documents, expiry, training/assessment, pause controls | Partner tab 4 | `GET /api/v1/partners/me`, `/documents` |
| OpsLogin | A/O | Staff login (MFA enforcement point) | Ops stack | `POST /api/v1/auth/otp/request` (staff), `/verify` |
| OpsJobBoard | O | Live jobs, exception queue (unassigned/late/failed-payment/unsafe-site/damage) | Ops tabs | `GET /api/v1/ops/jobs`, `GET /api/v1/ops/exceptions` |
| OpsJobDetail | O | Full timeline, events, manual assign, reassign with reason, override with reason | Stack | `GET /api/v1/ops/jobs/{id}`, `POST .../assign`, `.../override` |
| OpsPartnerApprovals | O | Approve/suspend, verification docs, expiries | Ops tabs | `GET /api/v1/ops/partners`, `POST .../{id}/approve|suspend` |
| OpsZones | O | Zone polygons, service windows, capacity caps, site restrictions | Ops tabs | `GET/POST/PATCH /api/v1/ops/zones` |
| OpsCatalog | O | Services, add-ons, price rule versions | Ops tabs | `GET/POST/PATCH /api/v1/ops/services`, `/price-rules` |
| OpsRefunds | O | Refund/partial refund with approval limit + reason | Stack | `POST /api/v1/ops/refunds` |
| OpsSupportCases | O | Case queue, evidence freeze, SLA deadlines, escalation | Ops tabs | `GET/PATCH /api/v1/ops/support-cases` |
| OpsReconciliation | O | Daily provider reconciliation, unmatched webhooks, payout batches | Ops tabs | `GET /api/v1/ops/reconciliation`, `POST .../run` |
| OpsDashboards | O | The 8 pilot metrics + contribution per wash, by zone | Ops tabs | `GET /api/v1/ops/dashboards/pilot` |
| OpsAuditLog | O | Admin overrides with reasons | Ops tabs | `GET /api/v1/ops/audit` |

Existing placeholders and their disposition:

| Existing file | Disposition |
|---|---|
| `screens/PhoneVerificationScreen.tsx` | Replace → `app/(auth)/phone.tsx` (flow preserved: phone → OTP) |
| `screens/OtpVerificationScreen.tsx` | Replace → `app/(auth)/otp.tsx` (adds resend/cooldown/attempts) |
| `screens/UserTypeSelectionScreen.tsx` | Replace → role choice inside `app/(auth)/register/*` |
| `screens/UserRegistrationScreen.tsx` | Replace → `app/(auth)/register/customer.tsx` (RHF+Zod, no inline fetch) |
| `screens/VendorRegistrationScreen.tsx` | Replace → `app/(auth)/register/partner.tsx` |
| `screens/UserDashboardScreen.tsx` | Replace → `app/(customer)/index.tsx` + sub-screens |
| `screens/VendorDashboardScreen.tsx` | Replace → `app/(partner)/index.tsx` + sub-screens |
| `screens/WashingSchemesScreen.tsx` | Replace → `app/(customer)/services.tsx` (now backed by real catalog API) |
| `App.tsx` | **Delete** — dead code. `package.json` `main` is `expo-router/entry`, so this file never loads; it also mounts a second, conflicting React Navigation tree. |
| `components/themed-*.tsx`, `hooks/use-color-scheme*`, `constants/theme.ts`, `assets/images/*` | **Preserve and reuse.** |

---

## D. User flows

### F1 — Customer onboarding
`PhoneEntry` → `POST /auth/otp/request` → `OtpVerify` → `POST /auth/otp/verify` → 200 with tokens +
`account_complete=false` → `RegisterCustomer` (profile, address+pin, first vehicle) →
`POST /auth/register/customer` → refresh tokens → `CustomerHome`.
Error branches: rate-limited (cooldown shown), wrong OTP (attempts remaining), expired OTP, blocked number.

### F2 — Partner onboarding & approval (PDF §05 Partner readiness)
`ApplyPartner` (identity, payout account, business docs w/ **expiry dates**, skills, equipment kit,
site permissions) → `POST /auth/register/partner` → status `pending_verification` → uploads documents
→ ops `OpsPartnerApprovals` verifies → `approved` **but offers still suspended** until training +
kit checklist + practical assessment complete (`partner_is_eligible_for_offers()` requires all of:
verified ∧ insurance valid ∧ kit current ∧ assessment passed ∧ no suspension).
"Suspend new offers when certification, required kit or insurance status expires."

### F3 — Quote → book → authorise (the core "Choose/Confirm" journey)
`CustomerHome` → `Garage` (add vehicle) → `Addresses` (pin + site type + access notes) →
`ServiceCatalog` (site-type-filtered) → `QuoteBuilder` (add-ons, time window) → `POST /quotes`
→ server validates site/method compatibility, zone membership, capacity; prices itemised →
`QuoteReview` (total, expected duration, inclusions/exclusions, expiry) → accept terms →
`POST /bookings` **with `Idempotency-Key`** → booking created `requested`, quote **locked** →
`POST /payments/authorizations` → provider tokenised, **no raw card data touches our DB** →
booking `quote_accepted` → dispatch begins. Customer sees **no arrival promise yet** (PDF: *"receive a
realistic arrival window only after partner assignment"*).

### F4 — Dispatch → assignment
Server-side `dispatch` service: eligibility filter (zone polygon, open hours, service type, partner
status, skills/equipment, capacity, travel limit, site restrictions) → candidate ranking (road ETA +
predicted arrival reliability, then fairness factor for workload & recent offer history) → create
time-limited `DispatchOffer`s (one, or a small batch) → **atomic** first-valid-acceptance booking lock
(`SELECT ... FOR UPDATE` + status guard) → `assigned`, partner notified, customer promise window
published. Expiry/retry/widen within configured caps. Stale-location and missed-milestone detection
raises an ops alert **before** automatic reassignment.

### F5 — Fulfilment (partner job loop)
`OfferDetail` (countdown, payout estimate, vehicle/service, access notes) → **accept** (or decline →
widen search) → `ActiveJob` → **navigate** (external maps handoff) → **mark arrived** →
**verify customer or booking code** → `GuidedEvidenceCapture` pre-service (lighting, angle, vehicle
identity checks enforced; customer confirmation of vehicle + pre-existing condition when present;
no-contact flow with clear proof + support route) → **start** → `Checklist` →
after-photos → **complete**. All transitions timestamped + attributed in `BookingEvent`.
Guards: cannot `start` without pre-evidence; cannot `complete` without after-evidence + checklist.

### F6 — Completion → capture → payout eligibility
`complete` → server computes/validates final = locked quote (any change needs customer approval) →
`payment_captured` → `partner_payout_eligible` → payable row created → included in next `PayoutBatch`
→ daily reconciliation against provider/payout file; mismatches surface in `OpsReconciliation`.

### F7 — Cancellation / refund / reassignment
Customer cancels → cancellation-policy computation (fee/no-fee) → `Cancellation` row + `BookingEvent` →
if captured, `Refund` (full/partial) with approver recorded → ledger entries posted → partner notified.
Reassignment: guarded so it "must not create duplicate partner work or payment capture" — the booking
lock and the payment authorization are single-owner; a partner whose offer was superseded has their
active-job write access revoked in the same transaction.

### F8 — Dispute / damage
`JobReport` (issue / damage / unsafe site / emergency) → `SupportCase` (priority, SLA deadline,
status) → **evidence freeze** (blocks evidence deletion) → human-led process: response deadline →
partner/insurer escalation → refund authority decision → customer updates. Image models explicitly
do **not** decide liability (PDF: *"must not decide liability"*) — no auto-adjudication is implemented.

### F9 — Ops exception queue
Unassigned past threshold / late partner / failed payment / unsafe site / damage → appear in
`OpsJobBoard` → manual assignment or override **with reason** → `AdminAuditLog` row written in the
same transaction. Zone or partner can be paused from the console.

### F10 — Partner availability & privacy-controlled location
`ShiftAndRadius` → set shift + radius + capacity → `on_shift=true` → location updates accepted
(with timestamp, accuracy) → stale/out-of-order updates **rejected** → off-duty: collection stops,
visible off-duty state, retention minimised.

---

## E. Database model

Conventions: UUID primary keys; `created_at`/`updated_at` (UTC); soft-delete only where retention
matters; money as **integer minor units + currency** (PDF §04 Money); no DB blobs for images.

### identity

**User** — `id`, `phone` (unique, E.164), `email`(nullable), `full_name`, `is_active`,
`is_staff`, `phone_verified_at`, `last_login_at`, `account_complete`, `consent_accepted_at`,
`consent_version`, `anonymized_at`, timestamps.
Indexes: `phone` (unique), `phone_verified_at`.

**RoleGrant** — `user` FK, `role` (enum: `customer|partner|ops|admin`), `granted_by` FK User,
`granted_at`, `revoked_at`(nullable). Unique: `(user, role)` where not revoked.

**OtpChallenge** — `phone`, `code_hash`, `purpose` (`login|register`), `attempts`, `max_attempts`,
`expires_at`, `consumed_at`, `request_ip`, timestamps. Index: `(phone, purpose, expires_at)`.

**RefreshToken** — `user` FK, `token_hash`, `family` (rotation/reuse-detection), `expires_at`,
`revoked_at`, `replaced_by`, `user_agent`, `ip`. Index: `token_hash` (unique), `user`.

**PartnerProfile** — `user` FK (OneToOne), `status` (`draft|pending_verification|approved|suspended|rejected`),
`display_name`, `bio`, `phone_verified`, `payout_account_ref` (provider token, never bank details),
`payout_provider`, `commission_bps`, `rating_avg`, `rating_count`, `rating_visible`,
`insurance_expires_at`, `certification_expires_at`, `assessment_passed_at`, `suspended_at`,
`suspension_reason`, timestamps.
Indexes: `status`, `insurance_expires_at`, `certification_expires_at`, `rating_avg`.

**PartnerDocument** — `partner` FK, `doc_type` (`identity|business_registration|insurance|payout_account|police_check|other`),
`object_key`, `checksum`, `issued_at`, `expires_at`, `verification_status` (`pending|verified|rejected`),
`verified_by` FK User, `verified_at`, `rejection_reason`.
Constraint: identity documents are **not** readable by `ops` support role — only `admin`/verifier.
Indexes: `partner`, `expires_at`, `verification_status`.

**ConsentRecord** — `user` FK, `consent_type` (`terms|privacy|location|marketing|evidence`),
`granted` bool, `version`, `granted_at`, `ip`, `user_agent`.

**NotificationPreference** — `user` OneToOne, `push_enabled`, `email_enabled`, `sms_enabled`,
`booking_updates`, `assignment_alerts`, `offer_alerts`, `marketing`, `quiet_hours_start/end`.

**Device** (push tokens) — `user` FK, `expo_push_token`(unique), `platform`, `active`,
`last_seen_at`.

### supply / catalog

**Vehicle** (garage entry) — `owner` FK User, `vehicle_type` (`car|suv|truck|van|bike|scooter`),
`make`, `model`, `year`, `color`, `registration_number`, `license_plate_hash`, `size_tier`
(`S|M|L|H`, derived), `is_default`, `is_active`, timestamps. Indexes: `owner`, `(owner, is_active)`.

**ServiceType** — `code` (unique), `name`, `description`, `base_price_minor`, `currency`,
`expected_duration_minutes`, `allowed_site_types` (Array), `allowed_vehicle_tiers` (Array),
`requires_water_source`, `requires_power_source`, `is_active`.
Enables the PDF rule "block unsupported methods at a site type".

**AddOn** — `code` (unique), `name`, `description`, `price_minor`, `currency`, `duration_delta_minutes`,
`allowed_service_codes` (Array), `allowed_site_types` (Array), `is_active`.

**PriceRuleVersion** — `version` (unique), `effective_from`, `effective_to`(nullable), `rules` (JSON:
tier multipliers, zone/travel component, tax bps, platform fee, discount rules), `created_by`,
`is_locked`. Quotes store `price_rule_version` FK → satisfies "store each line and the ruleset version".

**QuoteLine** — `quote` FK, `line_type` (`service_base|vehicle_tier|addon|zone_travel|tax|fee|discount`),
`ref_code`, `description`, `quantity`, `unit_price_minor`, `amount_minor`, `sort_order`.

**Quote** — `customer` FK, `vehicle` FK, `address` FK, `service` FK, `booking_mode`
(`scheduled|on_demand`), `window_start`, `window_end`, `status`
(`draft|quoted|accepted|expired|declined|locked|superseded`), `subtotal_minor`, `tax_minor`,
`fee_minor`, `discount_minor`, `total_minor`, `currency`, `price_rule_version` FK,
`expected_duration_minutes`, `inclusions` (JSON), `exclusions` (JSON), `expires_at`,
`accepted_at`, `locked_at`, `idempotency_key`.

**ServiceZone** — `code` (unique), `name`, `city`, `polygon_geojson` (JSON), `bbox_min_lat/lng`,
`bbox_max_lat/lng` (indexed for fast pre-filter), `is_active`, `max_concurrent_jobs`,
`on_demand_enabled`, `on_demand_radius_km`, `booking_cap`, `timezone`, timestamps.
Indexes: `code`, `is_active`, bbox columns.

**ZoneServiceWindow** — `zone` FK, `weekday` (0–6), `opens_at`, `closes_at`,
`allows_scheduled`, `allows_on_demand`, `max_jobs`. Constraint: unique `(zone, weekday)`.

**SiteRestriction** — `zone` FK (nullable = global), `site_type`
(`standalone_house|apartment|basement|commercial|society`), `allowed_service_codes` (Array),
`prohibited_service_codes` (Array), `notes`, `requires_property_approval`.

### partner supply

**PartnerServiceSkill** — `partner` FK, `service` FK, `proficiency` (`trained|assessed|expert`),
`certified_at`, `expires_at`. Unique `(partner, service)`.

**PartnerEquipmentItem** — `partner` FK, `item_code`, `name`, `required` bool, `status`
(`present|missing|expired`), `expires_at`, `checked_at`, `checked_by`.

**PartnerShift** — `partner` FK, `starts_at`, `ends_at`, `declared_capacity_minutes`,
`zone` FK, `status` (`planned|active|ended|cancelled`), `ended_actual_at`.
Constraint: no overlapping shifts per partner (validated in service layer).

**PartnerAvailabilityWindow** — `partner` FK, `weekday`, `starts_at`, `ends_at`, `is_available`.

**PartnerLocationPing** — `partner` FK, `lat`, `lng`, `accuracy_m`, `recorded_at` (client timestamp),
`shift` FK (nullable), `booking` FK (nullable), `is_active_context` bool.
Rules: reject `recorded_at` older than last accepted ping (out-of-order/stale); reject when neither
on-shift nor active job. **Minimise retention** → scheduled pruning job (configurable retention window).
Indexes: `(partner, recorded_at desc)`.

### transaction

**Booking** — `reference` (unique, human-readable e.g. `CW-7F3K2A`), `customer` FK, `partner` FK (nullable until assigned),
`zone` FK, `service` FK, `vehicle` FK, `address` FK, `quote` FK (locked), `booking_mode`,
`status` (see state machine), `subtotal/tax/fee/discount/total_minor`, `currency`,
`price_rule_version` FK, `window_start`, `window_end`, `promise_window_start/end` (only set after assignment),
`scheduled_start`, `reassign_count`, `cancellation_policy_snapshot` (JSON),
`terms_accepted_at`, `terms_version`, `completed_at`, `cancelled_at`, `cancel_reason`,
`payout_eligible_at`, `rating`, `rating_comment`, `no_contact` bool, `idempotency_key`.
Indexes: `reference`(unique), `(customer, status)`, `(partner, status)`, `(status, window_start)`,
`(zone, scheduled_start)`, `idempotency_key`.

**BookingEvent** (append-only) — `booking` FK, `seq`, `from_status`, `to_status`, `event_type`,
`actor_type` (`customer|partner|ops|admin|system|provider`), `actor` FK User (nullable),
`reason`, `metadata` (JSON), `occurred_at`. **Append-only**: no update/delete via ORM.
Indexes: `(booking, seq)`, `occurred_at`.

**DispatchOffer** — `booking` FK, `partner` FK, `status`
(`pending|accepted|declined|expired|superseded|withdrawn`), `payout_estimate_minor`, `currency`,
`offered_at`, `expires_at`, `responded_at`, `rank`, `batch`, `eta_seconds`,
`declined_reason`. Constraint: unique `(booking, partner)`.
Indexes: `(partner, status, expires_at)`, `(booking, status)`.

**Cancellation** — `booking` OneToOne, `cancelled_by` FK User, `actor_role`, `reason_code`
(`customer|partner_no_show|unsafe_site|payment_failure|ops|duplicate`), `reason_text`,
`policy_snapshot` (JSON), `fee_minor`, `refund_required` bool, `occurred_at`.

**SupportCase** — `booking` FK (nullable), `opened_by` FK User, `assignee` FK User (nullable),
`category` (`issue|damage|unsafe_site|emergency|payment|no_show|other`),
`priority` (`low|normal|high|critical`), `status` (`open|triaged|awaiting_customer|awaiting_partner|
escalated|resolved|closed`), `evidence_frozen` bool, `frozen_at`, `sla_due_at`, `first_response_at`,
`resolution`, `refund_authority_used_minor`, `liability_decided_by` FK User (nullable),
`liability_outcome` (`partner|platform|customer|pending`), timestamps.
Indexes: `(status, priority)`, `booking`, `sla_due_at`.

**Acknowledgement** — `booking` FK, `party` (`customer|partner`), `user` FK, `kind`
(`pre_condition|arrival|completion`), `payload` (JSON), `created_at`.

### evidence

**JobEvidence** — `booking` FK, `evidence_type`
(`pre_condition|post_service|damage|other`), `uploader` FK User, `captured_at` (client),
`uploaded_at`, `upload_status` (`pending|uploading|uploaded|failed|quarantined|deleted`),
`object_key` (unique), `checksum_sha256`, `content_type`, `byte_size`, `width`, `height`,
`access_policy` (`customer_partner_ops|ops_only|admin_only`), `retention_deadline`,
`deleted_at`, `deletion_reason`, `sequence` (ordering for guided capture), `checks` (JSON:
lighting_ok, angle_ok, identity_confirmed), `client_photo_id` (idempotency).
Indexes: `(booking, evidence_type, sequence)`, `object_key`(unique), `retention_deadline`,
`upload_status`.
Never stored as a DB blob (§04).

### money

All amounts `*_minor` integer + `currency` char(3).

**PaymentMethodToken** — `user` FK, `provider`, `provider_token` (unique), `brand`, `last4`,
`expiry_month/year`, `is_default`, `created_at`. **No PAN/CVV ever stored.**

**PaymentAttempt** — `booking` FK, `attempt_type` (`authorize|capture|refund|void|payout`),
`status` (`created|requires_action|authorized|captured|failed|cancelled|expired`),
`amount_minor`, `currency`, `provider`, `provider_ref` (unique per provider), `idempotency_key`(unique),
`failure_code`, `failure_message`, `authorized_at`, `captured_at`, `failed_at`, `request_id`.

**LedgerEntry** (immutable, append-only) — `booking` FK (nullable), `account`
(`customer_cash|tax_payable|platform_fee|partner_payable|refund|promo|payment_fee|adjustment`),
`direction` (`debit|credit`), `amount_minor`, `currency`, `entry_type`
(`charge|capture|refund|payout|fee|tax|reversal|adjustment`), `payment_attempt` FK (nullable),
`refund` FK (nullable), `payout` FK (nullable), `memo`, `created_by` FK User (nullable),
`reversal_of` FK self (nullable), `occurred_at`. **No update/delete.**
Indexes: `(booking, occurred_at)`, `account`, `occurred_at`.

**Refund** — `booking` FK, `payment_attempt` FK, `amount_minor`, `currency`, `refund_type`
(`full|partial|cancellation_fee|damage|goodwill`), `reason_code`, `reason_text`,
`status` (`requested|approved|rejected|processing|succeeded|failed`),
`approved_by` FK User (nullable), `approved_at`, `provider_ref`, `idempotency_key`(unique), `failed_at`.

**PartnerPayable** — `booking` FK, `partner` FK, `gross_minor`, `commission_minor`,
`adjustment_minor`, `net_minor`, `currency`, `status`
(`accruing|eligible|scheduled|paid|on_hold|reversed`), `payout_batch` FK (nullable),
`eligible_at`, `hold_reason`. Unique `(booking, partner)`.

**PayoutBatch** — `reference` (unique), `period_start`, `period_end`, `status`
(`draft|approved|processing|paid|failed|reconciled`), `total_minor`, `currency`,
`partner_count`, `approved_by` FK User, `approved_at`, `provider_ref`, `paid_at`,
`reconciled_at`. Index: `status`, `period_end`.

**ReconciliationItem** — `batch`/`payout` FK (nullable), `provider` FK, `provider_event_id`
(unique), `kind` (`payout|charge|refund|chargeback|unmatched`), `expected_minor`, `actual_minor`,
`currency`, `status` (`matched|mismatch|missing_provider_event|unmatched_internal`),
`difference_minor`, `notes`, `resolved_by`, `resolved_at`, `raw` (JSON, redacted).
Index: `status`, `kind`.

**ProviderWebhookEvent** (persist-before-process) — `provider`, `provider_event_id`, `signature_valid`,
`event_type`, `payload` (JSON, redacted), `received_at`, `process_status`
(`received|processing|processed|failed|unmatched|duplicate`), `attempts`, `last_error`,
`processed_at`. **Unique `(provider, provider_event_id)`** for dedupe.

### cross-cutting

**IdempotencyRecord** — `key` (unique), `user` FK (nullable), `scope`, `request_fingerprint`,
`status` (`in_progress|completed|failed`), `response_code`, `response_body` (JSON), `created_at`,
`expires_at`. Enforces PDF "idempotency keys for create/capture/refund".

**OutboxEvent** (transactional outbox) — `topic`, `aggregate_type`, `aggregate_id`, `payload` (JSON),
`status` (`pending|processing|delivered|failed|dead_letter`), `attempts`, `max_attempts`,
`next_attempt_at`, `created_at`, `delivered_at`, `last_error`. Index: `(status, next_attempt_at)`.

**Notification** — `user` FK, `topic`, `title`, `body`, `data` (JSON), `booking` FK (nullable),
`read_at`, `created_at`, `push_sent_at`, `push_error`. Index: `(user, read_at)`, `(user, created_at desc)`.

**AdminAuditLog** (append-only) — `actor` FK User, `actor_role`, `action`, `target_type`,
`target_id`, `reason` (**required** for corrections/overrides), `before` (JSON), `after` (JSON),
`request_id`, `ip`, `created_at`. Index: `(target_type, target_id)`, `created_at`.

**RequestAudit** — `request_id` (unique), `user` FK (nullable), `method`, `path`, `status_code`,
`duration_ms`, `ip`, `user_agent`, `created_at`. Backs "request IDs".

**ChatThread / ChatMessage** — `Thread`: `booking` OneToOne, `customer` FK, `partner` FK,
`status` (`open|closed|expired`), `opened_at`, `closes_at` (active booking + short support window),
`last_message_at`. `Message`: `thread` FK, `sender` FK User, `body`, `created_at`, `read_at`.
Indexes: `thread, created_at`; `(status, closes_at)` for expiry.

**CallRelaySession** — `booking` FK, `caller` FK User, `callee` FK User, `provider`,
`provider_session_ref`, `masked_number`, `started_at`, `ended_at`, `duration_seconds`.
No raw numbers persisted by us.

**Rating** — folded onto `Booking` (single rating per booking, post-completion only).

---

## F. API specification

Base path `/api/v1`. All responses JSON. All timestamps ISO-8601 UTC. All money `{amount_minor, currency}`.

**Global conventions**
- Auth: `Authorization: Bearer <access_token>` (JWT, short-lived, HS256/RS256 via env).
  Refresh: `POST /auth/refresh` with rotating refresh token in HttpOnly-equivalent secure storage.
- `X-Request-Id` echoed; generated if absent; present in all logs.
- `Idempotency-Key` header required on all `POST` create/capture/refund commands.
- Rate limits (per user or IP): OTP 5/15min; quote 30/min; booking 10/hour; location 60/min when active
  context else 0; evidence upload 40/hour; chat 60/5min. Exceeded → `429` + `Retry-After`.
- Errors: `{"error": {"code": "<stable_machine_code>", "message": "...", "details": {...}, "request_id": "..."}}`
- Pagination: `?page=&page_size=` (max 100) → `{count, next, previous, results}`.
- Filtering/sorting where required: bookings `?status=&zone=&from=&to=&booking_mode=&ordering=`;
  offers `?status=`; evidence `?evidence_type=`.
- **Ownership + role enforced server-side on every endpoint** (PDF explicit).

**Stable error codes** (representative): `unauthenticated`, `permission_denied`, `validation_error`,
`not_found`, `invalid_state_transition`, `quote_expired`, `quote_not_accepted`, `offer_expired`,
`offer_already_responded`, `booking_already_assigned`, `location_context_inactive`,
`location_update_stale`, `site_method_not_permitted`, `zone_inactive`, `zone_capacity_reached`,
`on_demand_not_available`, `partner_not_eligible`, `evidence_incomplete`, `checklist_incomplete`,
`payment_authorization_failed`, `already_captured`, `refund_exceeds_captured`,
`refund_approval_limit_exceeded`, `payout_already_processed`, `override_reason_required`,
`idempotency_key_reuse_mismatch`, `rate_limited`, `webhook_signature_invalid`, `webhook_duplicate`.

---

### G1 Authentication

| Method | URL | Auth | Body | Query | Response | Codes |
|---|---|---|---|---|---|---|
| POST | `/auth/otp/request` | No | `{phone, purpose: login\|register}` | – | `202 {challenge_id, expires_at, retry_after_seconds, resend_available_at}` | 400 invalid phone; 429 rate limited; 409 already verified |
| POST | `/auth/otp/verify` | No | `{challenge_id, code}` | – | `200 {access_token, refresh_token, expires_in, user{id, roles[], account_complete}, next: complete_profile\|register_customer\|register_partner\|home}` | 400 invalid code; 410 expired; 423 locked (max attempts) |
| POST | `/auth/otp/resend` | No | `{challenge_id}` | – | `202 {expires_at, retry_after_seconds}` | 429 |
| POST | `/auth/refresh` | Refresh token | `{refresh_token}` | – | `200 {access_token, refresh_token, expires_in}` | 401 invalid/reused/revoked |
| POST | `/auth/logout` | Bearer | `{refresh_token?}` | – | `204` | – |
| POST | `/auth/register/customer` | Bearer (provisional) | `{full_name, email?, address{line1,line2?,city,state,postal_code,country,lat,lng,site_type}, vehicle{vehicle_type,make,model,year?,color?,registration_number?}, consent{terms,privacy,evidence}}` | – | `201 {user, vehicle, address}` | 400 validation; 409 phone already registered |
| POST | `/auth/register/partner` | Bearer (provisional) | `{display_name, bio?, skills[service_code], equipment[item_code], payout_account_ref, commission_ack, consent{...}}` | – | `201 {partner{status: pending_verification}}` | 400; 409 |
| POST | `/auth/staff/mfa` | Bearer (staff) | `{code}` | – | `200 {access_token, refresh_token}` | 401; 423 locked |

Notes: `consent` booleans + version are mandatory; `terms_accepted_at` recorded at booking too.

### G2 Profile / vehicles / addresses

| Method | URL | Auth | Body / Query | Response | Codes |
|---|---|---|---|---|---|
| GET | `/me` | Bearer | – | `200 {id, phone, email, full_name, roles[], account_complete, partner?}` | – |
| PATCH | `/me` | Bearer | `{full_name?, email?}` | `200 {user}` | 400 |
| GET/PATCH | `/me/preferences` | Bearer | – / push/sms/email/quiet hours toggles | `200 {preferences}` | – |
| POST | `/me/consents` | Bearer | `{consent_type, granted, version}` | `201 {consent}` | 400 |
| POST | `/me/data-requests` | Bearer | `{kind: export\|delete}` | `202 {request_id, status}` | 400 — privacy deletion/support path |
| GET | `/vehicles` | Bearer | – | `200 [Vehicle]` | – |
| POST | `/vehicles` | Bearer | `{vehicle_type, make, model, year?, color?, registration_number?, is_default?}` | `201 {vehicle}` | 400; 409 default conflict |
| PATCH/DELETE | `/vehicles/{id}` | Bearer (owner) | partial / – | `200 {vehicle}` / `204` | 403; 404; 409 (in active booking) |
| GET | `/addresses` | Bearer | – | `200 [Address]` | – |
| POST | `/addresses` | Bearer | `{line1, line2?, city, state, postal_code, country, lat, lng, site_type, access_notes?, parking_details?, property_approval?, is_default?}` | `201 {address}` | 400 (lat/lng range, site_type) |
| PATCH/DELETE | `/addresses/{id}` | Bearer (owner) | partial | `200` / `204` | 403; 404; 409 |

### G3 Catalog & zones (public read)

| Method | URL | Auth | Query | Response | Codes |
|---|---|---|---|---|---|
| GET | `/catalog/services` | Optional | `site_type`, `vehicle_type`, `zone` | `200 [ServiceType]` | – |
| GET | `/catalog/services/{code}` | Optional | – | `200 {service, addons[]}` | 404 |
| GET | `/catalog/addons` | Optional | `service_code` | `200 [AddOn]` | – |
| GET | `/zones` | Optional | `city`, `lat`, `lng` | `200 [Zone{code,name,is_active,service_windows}]` | – |
| GET | `/zones/{code}/availability` | Optional | `date`, `vehicle_size_tier` | `200 {windows[], slots[], on_demand_available, capacity_remaining}` | 404 |

### G4 Quotes

| Method | URL | Auth | Body | Query | Response | Codes |
|---|---|---|---|---|---|---|
| POST | `/quotes` | Bearer (customer) | `{vehicle_id, address_id, service_code, addon_codes[], booking_mode, window_start?, window_end?, coupon_code?}` | – | `201 {quote{id, reference, lines[], subtotal, tax, fee, discount, total, currency, expected_duration_minutes, inclusions, exclusions, expires_at, price_rule_version}}` | 400 validation; 403 `site_method_not_permitted`; 409 `zone_inactive`/`zone_capacity_reached`/`on_demand_not_available`; 422 outside service window |
| GET | `/quotes/{id}` | Bearer (owner) | – | – | `200 {quote}` | 403; 404; 410 `quote_expired` |
| POST | `/quotes/{id}/accept` | Bearer (owner) | `{terms_version}` | – | `200 {quote{status: accepted}}` | 410 expired; 409 not quoted |
| GET | `/quotes/price-rules/current` | Optional | – | – | `200 {version, rules}` | – |

Validation: server recomputes every line (never trusts client totals); stores `price_rule_version`.

### G5 Bookings (commands)

All require `Idempotency-Key`.

| Method | URL | Auth | Body | Response | Codes |
|---|---|---|---|---|---|
| POST | `/bookings` | Bearer (customer) | `{quote_id, terms_accepted: true, cancellation_policy_accepted: true, no_contact?}` | `201 {booking{id, reference, status: requested, total, window, promise_window: null}}` | 400; 403; 409 `quote_not_accepted`/`quote_expired`/`zone_capacity_reached`; 429 |
| GET | `/bookings` | Bearer | `status`, `booking_mode`, `zone`, `from`, `to`, `page`, `page_size`, `ordering` | `200 paginated [Booking]` | – |
| GET | `/bookings/{reference}` | Bearer (customer/partner/ops) | – | `200 {booking, service, vehicle, address, partner?, quote, payments[], evidence_summary, can_cancel, next_actions[]}` | 403; 404 |
| GET | `/bookings/{reference}/events` | Bearer (party) | – | `200 [BookingEvent]` (append-only) | 403; 404 |
| GET | `/bookings/{reference}/transitions` | Bearer (party) | – | `200 {allowed_transitions[], current}` | 403 |
| POST | `/bookings/{reference}/cancel` | Bearer (customer) | `{reason_code, reason_text?}` | `200 {booking{status: cancelled}, cancellation, refund?}` | 403; 409 `invalid_state_transition`; 422 policy window closed |
| POST | `/bookings/{reference}/arrival-confirmation` | Bearer (customer) | `{kind: pre_condition\|arrival, vehicle_confirmed, condition_confirmed, notes?, no_contact_proof?}` | `201 {acknowledgement}` | 409 not arrived yet |
| POST | `/bookings/{reference}/rating` | Bearer (customer) | `{rating: 1..5, comment?}` | `200 {booking{rating}}` | 409 not completed; 400 range |
| POST | `/bookings/{reference}/issue` | Bearer (any party) | `{category, priority?, description, evidence_ids[]?}` | `201 {support_case}` | 400 |
| POST | `/bookings/{reference}/acknowledge` | Bearer | `{kind, payload}` | `201 {acknowledgement}` | 409 |

### G6 Partner operations

| Method | URL | Auth | Body | Response | Codes |
|---|---|---|---|---|---|
| GET | `/partners/me` | Bearer (partner) | – | `200 {partner, readiness{verified, insurance_valid, kit_current, assessment_passed, eligible_for_offers, blockers[]}}` | – |
| PUT | `/partners/me/availability` | Bearer (partner) | `{shift{starts_at, ends_at, declared_capacity_minutes, zone_code}, availability_windows[], service_radius_km, capacity}` | `200 {partner, shift}` | 400 overlap/validation |
| POST | `/partners/me/location` | Bearer (partner) | `{lat, lng, accuracy_m, recorded_at}` | `202 {accepted, last_accepted_at, retention_until}` | 403 `location_context_inactive`; 409 `location_update_stale`; 400 range |
| PUT | `/partners/me/skills` | Bearer (partner) | `{skills[{service_code, proficiency}]}` | `200 {skills[]}` | 400 |
| PUT | `/partners/me/equipment` | Bearer (partner) | `{items[{item_code, status, expires_at?}]}` | `200 {items[]}` | 400 |
| GET | `/partners/me/documents` | Bearer (partner) | – | `200 [PartnerDocument]` | – |
| POST | `/partners/me/documents` | Bearer (partner) | multipart `{doc_type, file, issued_at?, expires_at?}` | `201 {document}` | 400 invalid type/size; 415 |
| POST | `/partners/me/documents/{id}/submit` | Bearer (partner) | – | `200 {document}` | 409 |
| GET | `/partners/me/earnings` | Bearer (partner) | `from`, `to` | `200 {summary{gross, commission, adjustments, net, currency}, payables[], payout_batches[]}` | – |
| GET | `/partners/me/payables` | Bearer (partner) | `status` | `200 [PartnerPayable]` | – |
| POST | `/partners/me/unavailability` | Bearer (partner) | `{from, to, reason_code}` | `201 {unavailability}` | 400 |

### G7 Dispatch & active job

| Method | URL | Auth | Body | Response | Codes |
|---|---|---|---|---|---|
| GET | `/dispatch/offers` | Bearer (partner) | `status` | `200 [DispatchOffer{booking summary, payout_estimate, expires_at, countdown, access_notes, vehicle, service}]` | – |
| POST | `/dispatch/offers/{id}/accept` | Bearer (partner, Idempotency-Key) | – | `200 {booking{status: assigned, promise_window}}` | 403 not offered to you; 409 `offer_expired`/`offer_already_responded`/`booking_already_assigned`; 404 |
| POST | `/dispatch/offers/{id}/decline` | Bearer (partner) | `{reason_code?}` | `200 {offer{status: declined}}` | 409 already responded |
| GET | `/bookings/{reference}/job` | Bearer (assigned partner) | – | `200 {job{checklist[], required_evidence[], customer_masked_contact, navigation_target, allowed_transitions[]}}` | 403 not assigned |
| POST | `/bookings/{reference}/arrive` | Bearer (partner) | `{arrived_at, booking_code?}` | `200 {booking{status: arrived}}` | 403; 409 `invalid_state_transition`; 400 bad code |
| POST | `/bookings/{reference}/start` | Bearer (partner) | `{started_at}` | `200 {booking{status: in_service}}` | 409 `evidence_incomplete` if pre-evidence missing |
| POST | `/bookings/{reference}/checklist` | Bearer (partner) | `{items[{code, done, notes?}], all_done?}` | `200 {checklist}` | 400 |
| POST | `/bookings/{reference}/evidence` | Bearer (partner/customer, Idempotency-Key) | multipart `{evidence_type, file, captured_at, client_photo_id, sequence?, checks?}` | `201 {evidence}` | 400 invalid content type/size/checksum; 415; 409 sequence conflict |
| GET | `/evidence/{id}/file` | Bearer (policy) | – | `200` binary (short-lived signed) | 403 `permission_denied`; 404; 410 deleted |
| POST | `/bookings/{reference}/complete` | Bearer (partner, Idempotency-Key) | `{completed_at, notes?, checklist_confirmed: true}` | `200 {booking{status: completed}, payment, payable}` | 409 `evidence_incomplete`/`checklist_incomplete`; 422 price change needs approval |
| POST | `/bookings/{reference}/report` | Bearer (any party) | `{category: unsafe_site\|damage\|emergency, description, lat?, lng?}` | `201 {support_case}` | 400 |

### G8 Payments (customer-facing tokenisation + status)

| Method | URL | Auth | Body | Response | Codes |
|---|---|---|---|---|---|
| POST | `/payments/methods` | Bearer | `{provider, provider_token, brand?, last4?, expiry_month?, expiry_year?}` | `201 {method{id, brand, last4, expiry}}` | 400 — **provider token only, never PAN/CVV** |
| GET | `/payments/methods` | Bearer | – | `200 [method]` | – |
| DELETE | `/payments/methods/{id}` | Bearer | – | `204` | 404 |
| POST | `/payments/authorizations` | Bearer (customer, Idempotency-Key) | `{booking_reference, payment_method_id, amount?}` | `201 {payment_attempt{id, status, amount, currency}}` | 400; 409 `quote_locked`/amount mismatch; 422 `payment_authorization_failed` |
| POST | `/payments/{id}/capture` | ops/provider (Idempotency-Key) | `{amount_minor?}` | `200 {payment_attempt{status: captured}}` | 403; 409 `already_captured` |
| POST | `/payments/{id}/void` | ops (Idempotency-Key) | `{reason_code}` | `200 {payment_attempt{status: cancelled}}` | 403; 409 |
| GET | `/bookings/{reference}/payments` | Bearer (party) | – | `200 {attempts[], refunds[], ledger[]}` | 403 |

Money endpoints enforce **idempotency**, single-capture, and refund ≤ captured amount, server-side.

### G9 Comms (masked)

| Method | URL | Auth | Body | Response | Codes |
|---|---|---|---|---|---|
| GET | `/comms/threads` | Bearer | – | `200 [Thread{booking_reference, status, closes_at}]` | – |
| GET | `/comms/threads/{booking_reference}/messages` | Bearer (party) | `page` | `200 [Message]` | 403; 404; 410 window closed |
| POST | `/comms/threads/{booking_reference}/messages` | Bearer (party) | `{body}` | `201 {message}` | 403; 410 `comms_window_closed`; 429 |
| POST | `/comms/threads/{booking_reference}/call` | Bearer (party) | – | `201 {call_relay{masked_number, expires_at, provider}}` | 403; 410; 429 |

Masking: raw customer/partner numbers are **never returned**; relay returns a masked/proxied number.
Thread auto-closes at `closes_at` = completion + short support window (configurable).

### G10 Notifications

| Method | URL | Auth | Body | Response | Codes |
|---|---|---|---|---|---|
| GET | `/notifications` | Bearer | `unread_only`, `page` | `200 [Notification]` | – |
| PATCH | `/notifications/{id}/read` | Bearer | – | `200 {notification}` | 404 |
| POST | `/notifications/read-all` | Bearer | – | `204` | – |
| POST | `/devices` | Bearer | `{expo_push_token, platform}` | `201 {device}` | 400 |
| DELETE | `/devices/{id}` | Bearer | – | `204` | 404 |

### G11 Operations console API

| Method | URL | Auth | Body / Query | Response | Codes |
|---|---|---|---|---|---|
| GET | `/ops/jobs` | ops/admin | `status`, `zone`, `unassigned`, `late`, `from`, `to`, `page` | `200 [Booking+ops fields]` | – |
| GET | `/ops/exceptions` | ops/admin | `type` (unassigned\|late\|failed_payment\|unsafe_site\|damage\|stale_location) | `200 [Exception{booking, type, severity, age_seconds}]` | – |
| POST | `/ops/jobs/{reference}/assign` | ops/admin | `{partner_id, reason}` | `200 {booking{status: assigned}}` | 409 already assigned; 403 partner not eligible; 400 |
| POST | `/ops/jobs/{reference}/reassign` | ops/admin | `{partner_id, reason}` | `200 {booking}` | 400 `override_reason_required` |
| POST | `/ops/jobs/{reference}/override` | ops/admin | `{to_status, reason}` | `200 {booking, audit_id}` | 400 reason required; 409 invalid transition |
| GET | `/ops/partners` | ops/admin | `status`, `expiring` | `200 [Partner+readiness]` | – |
| POST | `/ops/partners/{id}/approve` | admin | `{reason?}` | `200 {partner}` | 409 already decided |
| POST | `/ops/partners/{id}/suspend` | ops/admin | `{reason}` | `200 {partner}` | 400 reason required |
| POST | `/ops/partners/{id}/documents/{doc_id}/verify` | admin | `{status, reason?}` | `200 {document}` | 400 |
| GET/POST/PATCH | `/ops/zones`, `/ops/zones/{id}` | admin | zone + windows + restrictions | `200/201` | 400 |
| POST | `/ops/zones/{id}/pause` | ops/admin | `{reason}` | `200 {zone}` | 400 |
| GET/POST/PATCH | `/ops/services`, `/ops/addons`, `/ops/price-rules` | admin | – | `200/201` | 400 |
| GET | `/ops/refunds` | ops/admin | `status` | `200 [Refund]` | – |
| POST | `/ops/refunds` | ops/admin (Idempotency-Key) | `{booking_reference, amount_minor, refund_type, reason_code, reason_text}` | `201 {refund}` | 400; 403 `refund_approval_limit_exceeded`; 422 `refund_exceeds_captured` |
| GET | `/ops/support-cases` | ops/admin | `status`, `priority`, `category` | `200 [SupportCase]` | – |
| PATCH | `/ops/support-cases/{id}` | ops/admin | `{status?, assignee?, evidence_frozen?, resolution?, liability_outcome?}` | `200 {support_case}` | 400 |
| GET | `/ops/reconciliation` | ops/admin | `status`, `kind` | `200 [ReconciliationItem]` | – |
| POST | `/ops/reconciliation/run` | ops/admin | `{date}` | `202 {run_id, matched, mismatched, unmatched}` | 400 |
| GET | `/ops/payouts` | ops/admin | `status` | `200 [PayoutBatch]` | – |
| POST | `/ops/payouts` | admin (Idempotency-Key) | `{period_start, period_end}` | `201 {payout_batch}` | 400 |
| POST | `/ops/payouts/{id}/approve` | admin | – | `200 {payout_batch}` | 403; 409 |
| GET | `/ops/dashboards/pilot` | ops/admin | `zone`, `from`, `to`, `group_by` | `200 {fulfilment, on_time_arrival, customer_rating, rework_refund, partner_utilization, contribution_margin, repeat, safety_trust}` | – |
| GET | `/ops/audit` | admin | `target_type`, `target_id`, `action`, `from`, `to` | `200 [AdminAuditLog]` | – |
| GET | `/ops/outbox` | admin | `status` | `200 [OutboxEvent]` | – |
| POST | `/ops/outbox/{id}/retry` | admin | – | `202 {outbox_event}` | 409 |
| GET | `/ops/webhooks` | admin | `process_status` | `200 [ProviderWebhookEvent]` | – |
| GET | `/ops/zones/{id}/matrix` | ops/admin | – | `200 {site_type × service permitted/blocked}` | – |

### G12 Provider webhooks (no user auth)

| Method | URL | Auth | Body | Response | Codes |
|---|---|---|---|---|---|
| POST | `/webhooks/payments/{provider}` | HMAC signature header | provider event | `202 {received: true, duplicate: bool}` | 401 `webhook_signature_invalid`; 400 |
| POST | `/webhooks/ops/{provider}` | HMAC signature header | provider event | `202` | 401; 400 |

Flow: verify signature → dedupe on `(provider, provider_event_id)` → **persist** → enqueue outbox event →
process idempotently → unmatched events surfaced in `OpsReconciliation`.

---

## G. Third-party integrations

| Integration | Purpose (PDF ref) | Interaction design | MVP status |
|---|---|---|---|
| **Payment provider** (marketplace + partner payout capable) | authorize, capture, refund, payout (§03) | `PaymentGateway` port/interface + `SandboxGateway` (default) and adapter for a real provider selected by env. Provider tokens only; webhook signature verification + event dedupe + daily reconciliation. **Provider integration replaceable** (PDF explicit). | Sandbox implemented; real provider = config + adapter (**[OPEN]** which provider) |
| **Push notification provider** | assignment, delay, arrival, start, completion, cancellation (§03) | `PushProvider` port; Expo push transport; delivery status tracked on `Notification`. In-app notification centre always works as fallback. | Implemented (Expo) |
| **Maps / geocoding / road ETA** | address pin, road ETA, navigation handoff (§02/§03) | `EtaProvider` port with `StraightLineSpeedEtaProvider` default (documented estimate) and a road-ETA adapter slot. Ranking uses ETA + reliability, never straight-line distance alone. Deep link to device maps for navigation handoff. | Port + fallback implemented; real provider = adapter (**[OPEN]** key) |
| **Private object storage** | evidence photos (§04) | `EvidenceStorage` port; `FileSystemEvidenceStorage` default; DB stores object key + checksum + retention metadata, never blobs. Signed, short-lived download URLs. **Not labelled immutable** (PDF explicit). | Implemented (filesystem, S3-compatible adapter slot) |
| **Masked communications provider** | masked call/chat (§03) | `CommsProvider` port; `FirstPartyRelayCommsProvider` (server proxies, returns masked number) + adapter slot. Window limited to active booking + short support window. | Implemented (first-party) |
| **Queue / background worker** | outbox, image processing, webhooks, reconciliation (§02) | Transactional outbox table + Django management command worker with bounded retries, backoff, dead-letter, operator visibility. Redis/Celery deliberately **not** introduced (PDF: Redis "is not the source of truth"); adapter slot if scale demands. | Implemented (management command) |
| **Redis** | presence, offer locks, rate limits (§02) | **Deferred.** Booking lock uses PostgreSQL row locks (`SELECT FOR UPDATE`), which is authoritative during the pilot per PDF. | Deferred |
| **PostGIS** | zone polygons, spatial matching (§02) | Zone polygon stored as GeoJSON + indexed bbox; point-in-polygon in Python. PostGIS upgrade path documented. | Deferred, flagged **[ASSUMPTION]** |
| **Kubernetes / microservices** | explicitly rejected for now (§02) | Modular monolith; split triggers documented. | Not built |

---

## Non-functional requirements (PDF-derived, testable)

1. **UTC storage, local rendering** for all timestamps; explicit currency everywhere (§04).
2. **Integer minor units** for all money (§04).
3. **Server-side state machine** — clients cannot skip states or alter accepted price (§04).
4. **Idempotency** on booking, offer acceptance, payment callbacks, completion (§02/§04).
5. **Bounded retries + dead-letter + operator visibility** for failed background jobs (§02).
6. **Request IDs** on every response and log line (§04).
7. **Rate limits** on sensitive endpoints (§04).
8. **Audit log for every admin override**, with reason (§01/§04).
9. **Location minimisation**: only on-shift or active-job; reject stale/out-of-order; short retention (§02/§04/§05).
10. **Visibility of staleness**: show last update time; never present stale GPS as live (§02).
11. **Idempotent webhooks**: signature verify, dedupe, persist-before-process, safe retry, surface unmatched (§04).
12. **Privacy deletion + export path**, documented retention, legal hold (§04/§05).
13. **Least-privilege RBAC**, staff MFA, encrypted transport, managed secrets, admin access logs (§05).
14. **Honest ETAs** — firm promise only after acceptance (§01/§03).
15. **Every state transition timestamped and attributed** (§01).
16. **No blanket water-saving claims** unless measured (§05) — copy must not assert unverified claims.
17. **Blocked methods at unsupported sites** — enforced, not advisory (§05).
18. **TypeScript strict mode**, strong validation on both sides.

---

## Error scenarios & edge cases (explicitly enumerated)

- OTP: rate limited, wrong code, exhausted attempts (lockout), expired, resend cooldown, already-verified number.
- Booking: quote expired between review and accept; capacity exhausted; zone paused mid-flow; site method not permitted; double-tap submit (idempotency); customer cancels during dispatch; cancel after capture (refund path); cancel outside policy window (fee or rejection).
- Dispatch: no eligible partners; single partner declines; offer expires at the moment of accept; two partners accept simultaneously (exactly one wins); stale location; missed milestone; partner becomes ineligible mid-offer; reassignment must not duplicate work or capture.
- Fulfilment: partner no-show; unsafe site discovered on arrival; customer absent; wrong booking code; insufficient light for photos; upload failure/partial upload; customer declines to confirm pre-condition (no-contact flow); checklist incomplete; after-photo missing.
- Money: authorization declined; insufficient funds; capture fails; partial capture; refund > captured; refund beyond approval limit; chargeback; payout batch fails; reconciliation mismatch; duplicate webhook; webhook signature invalid; double capture attempt.
- Privacy: location ping while off-shift; out-of-order ping; evidence access by wrong role; deletion request while evidence is under legal hold; data export request.
- Platform: network failure mid-request; offline booking attempt; server 500; expired access token mid-flow; refresh token reuse (family revocation); clock skew.
- Boundary conditions: max garage size; quote with all add-ons removed; zero-discount edge; rounding on tax; booking at exact window boundary; DST/timezone transition in a zone; very large evidence file; unsupported image format.

---

## H. Open questions / assumptions

### Blocking-ish (need your decision; I will proceed on the stated default if you don't object)

1. **Stack override — CONFIRMED BY YOU, applying.** PDF §02 recommends Flutter + NestJS + PostGIS. Your instruction mandates React Native/Expo + Django/DRF. I am following **your** stack and carrying over the PDF's *architectural principles* (modular monolith, server-side state machine, transactional outbox, idempotency, minor units, UTC, RBAC, audit). **Assumption:** Flutter/NestJS are non-binding suggestions in a "decision draft".
2. **Currency / locale.** PDF lists launch geography & currency as *decisions required before engineering is locked* and does not fix them. The existing scaffold hardcodes `country: 'India'`. **Assumption:** default `INR`, 2-decimal minor units, single launch city, `Asia/Kolkata` — fully env-configurable, no hardcoding.
3. **Operations console delivery.** PDF MVP requires a web ops console; your stack has no web front-end. **Assumption:** I deliver the *ops capability* as a fully permissioned, audited DRF operations API + Django admin (so a console can be built on it), and do **not** build a React web console. The mobile app covers customer + partner only.
4. **Single app, distinct experiences.** PDF: *"Keep customer and partner experiences distinct."* **Assumption:** one Expo app; auth routes to `(customer)`, `(partner)`, or `(ops)` groups by role; no role mixing in one session.
5. **PostGIS.** **Assumption:** store zone polygons as GeoJSON + indexed bbox columns and do point-in-polygon in Python now; document the PostGIS migration path. This keeps plain PostgreSQL as the only hard dependency.
6. **Payments.** PDF requires a locally-supported marketplace provider, undecided. **Assumption:** implement a `PaymentGateway` port with a working **sandbox** implementation (authorize/capture/refund/payout/webhook with signature verification + dedupe), selected by env var. No real provider keys, no real money movement.
7. **Road ETA.** **Assumption:** `EtaProvider` port with a documented straight-line + assumed-speed estimator as the default, explicitly labelled an estimate in the UI (honest-ETA rule). Real road-ETA adapter needs a provider key.
8. **Masked comms.** **Assumption:** server-side relay returning a masked number (no provider), plus real in-app chat, scoped to the active booking + configurable support window.
9. **Queue/Redis/Celery.** **Assumption:** transactional outbox + Django management-command worker; no Redis/Celery dependency. Rationale: PDF says Redis is not the source of truth; avoid unnecessary dependencies.
10. **Staff MFA.** PDF requires MFA for staff. **Assumption:** implement MFA as a server-enforced gate on staff login (TOTP-style code challenge) with the mobile app not shipping a staff-facing MFA enrollment UX in MVP; documented.
11. **Tax treatment.** PDF defers tax/worker classification to local advisers. **Assumption:** model tax as an explicit, configurable line item (`tax_bps` in the price rule version) that defaults to **0%** until a jurisdiction is confirmed — never hardcode a tax rate.
12. **Currency of existing scaffold naming (`Vendor`).** **Assumption:** rename to `partner` throughout for PDF alignment; the old `screens/` placeholders are deleted because they are non-functional (no backend exists) and violate the required architecture (inline `fetch`, hardcoded URL, duplicated styles, no validation). Reusable template assets are preserved.

### Non-blocking questions for later phases

13. Cancellation policy specifics (free-until window, late fee, partner no-show penalty) — configurable policy snapshot, defaults documented.
14. Which add-ons/services to seed for launch — I'll seed a defensible default catalog (Express Exterior, Interior, Full Detail) and make it ops-editable.
15. On-demand window & travel limit numbers — configurable caps, defaults documented.
16. Whether customers may book multiple vehicles in one job (default: no).
17. Rating vs. automated quality scoring — rating is MVP; automated image scoring is explicitly "Later".
18. Evidence retention duration — configurable, default documented, legal-hold capable.
19. Support-window length after completion for chat/call — configurable.
20. Whether a `no_contact` booking skips arrival code verification — default: requires alternative proof.

---

## Requirements explicitly OUT of MVP (must not be built)

Per §01 "Release boundary" — Later column: outlet discovery, bay calendars, walk-in POS, multi-tenant outlet inventory, outlet-specific staff roles; automated subscriptions, family/fleet accounts, advanced route batching, partner lending/equipment financing; predictive staffing, complex surge pricing, loyalty tiers, broad referral automation, multi-city tenancy; automated quality scoring from images, real-time location sharing outside active work, AI damage judgments; and §04 "Later" entities (subscription, outlet, bay, inventory lot, corporate account, referral attribution).
Also excluded: Kubernetes/microservices, weather/demand surcharges, image models deciding liability, blanket water-saving claims.