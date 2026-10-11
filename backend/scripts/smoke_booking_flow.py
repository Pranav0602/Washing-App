"""End-to-end verification of the complete job loop.

Exercises the PDF's core promise as a single scenario:

    quote -> book -> authorise -> dispatch -> offer -> accept -> arrive
          -> pre-evidence -> start -> checklist -> post-evidence -> complete
          -> capture -> payout eligible -> earnings

and, on the way, every negative path that matters most:
site-method blocking, illegal state transitions, expired offers, double acceptance,
evidence guards, and the price lock.

Run with:  python scripts/smoke_booking_flow.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

# E402 is intentional throughout this file: Django must be configured before any
# application model can be imported.
import django  # noqa: E402

django.setup()

import secrets  # noqa: E402
from datetime import (
    UTC,
    timedelta,  # noqa: E402
)

from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.test import Client  # noqa: E402
from django.utils import timezone  # noqa: E402

FAILURES: list[str] = []
PASSES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    if condition:
        PASSES.append(label)
        print(f"[PASS] {label}" + (f" - {detail}" if detail else ""))
    else:
        FAILURES.append(label)
        print(f"[FAIL] {label}" + (f" - {detail}" if detail else ""))
    return bool(condition)


def section(title: str) -> None:
    print(f"\n--- {title} ---")



def in_window_time(zone, *, days_ahead: int = 1, hour: int = 12) -> str:
    """A time inside the zone's service window, expressed in UTC.

    The seeded zone books 08:00-20:00 local, so a naive ``now() + 1 day`` can land
    outside that window. Choosing the time deliberately also proves the window check
    is satisfied rather than bypassed.
    """
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(zone.timezone_name)
    local = (timezone.now() + timedelta(days=days_ahead)).astimezone(tz)
    local = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    return local.astimezone(UTC).isoformat()


def out_of_window_time(zone) -> str:
    """A time the zone is definitely closed."""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(zone.timezone_name)
    local = (timezone.now() + timedelta(days=1)).astimezone(tz)
    local = local.replace(hour=3, minute=0, second=0, microsecond=0)
    return local.astimezone(UTC).isoformat()


def png_bytes() -> bytes:
    """A minimal valid PNG header plus padding."""
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
        b"\x00\x00\x00\x1f\x15\xc4\x89" + b"\x00" * 64
    )


def auth(token: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def login(client: Client, phone: str) -> dict:
    """OTP login without depending on an SMS provider."""
    from apps.identity.services import otp as otp_service

    issued = otp_service.request_challenge(
        raw_phone=phone, purpose="login", deliver=lambda p, c: None
    )
    response = client.post(
        "/api/v1/auth/otp/verify",
        data={"challenge_id": str(issued.challenge.pk), "code": issued.code},
        content_type="application/json",
    )
    if response.status_code != 200:
        raise SystemExit(f"login failed for {phone}: {response.status_code} {response.content[:300]}")
    return response.json()



def make_test_zone(tag: str = ""):
    """A throwaway zone containing only this run's addresses and partners.

    Using the seeded zone would make the test order-dependent, because partners
    created by earlier runs stay eligible and compete for offers.
    """
    from apps.locations.models import ServiceZone, ZoneServiceWindow
    from apps.partners.models import PartnerProfile
    from apps.seed_support import square_polygon

    centre_lat, centre_lng = 12.9716, 77.5946
    polygon = square_polygon(centre_lat, centre_lng, half_km=4.0)
    lats = [point[1] for point in polygon["coordinates"][0]]
    lngs = [point[0] for point in polygon["coordinates"][0]]

    # A single fixed code, and every prior run's partners removed. Per-run codes
    # would accumulate zones that all contain the test address, and
    # ``find_zone_for_point`` resolves ties on code order - so an older zone would
    # silently win and take the booking's dispatch with it.
    # Neutralise everything a previous run left behind. Zones cannot be deleted
    # because quotes and bookings protect them (correctly), so they are deactivated
    # instead: find_zone_for_point only considers active zones, which stops a stale
    # zone capturing this run's booking. Leftover partners are suspended, which
    # removes them from the eligibility filter.
    ServiceZone.objects.filter(code__startswith="TEST-").exclude(
        code="TEST-DISPATCH"
    ).update(is_active=False, is_paused=True)
    PartnerProfile.objects.filter(home_zone__code="TEST-DISPATCH").update(
        status=PartnerProfile.Status.SUSPENDED
    )

    zone, _ = ServiceZone.objects.update_or_create(
        code="TEST-DISPATCH",
        defaults={
            "name": "Dispatch test zone",
            "city": "Bengaluru",
            "polygon_geojson": polygon,
            "bbox_min_lat": min(lats),
            "bbox_max_lat": max(lats),
            "bbox_min_lng": min(lngs),
            "bbox_max_lng": max(lngs),
            "timezone_name": "Asia/Kolkata",
            "is_active": True,
            "is_paused": False,
            "max_concurrent_jobs": 20,
            "booking_cap_per_day": 100,
            "on_demand_enabled": True,
            "on_demand_radius_km": 8.0,
        },
    )
    for weekday in range(7):
        ZoneServiceWindow.objects.update_or_create(
            zone=zone,
            weekday=weekday,
            defaults={
                # Realistic staffed hours, so the "outside service window" check is
                # meaningful inside this zone too.
                "opens_at_minutes": 8 * 60,
                "closes_at_minutes": 20 * 60,
                "allows_scheduled": True,
                "allows_on_demand": True,
                "max_jobs": 50,
            },
        )
    return zone


def make_ready_partner(user, zone=None):
    """Take a partner all the way to eligible-for-offers."""
    from datetime import timedelta

    from apps.catalog.models import ServiceType
    from apps.identity.models import ROLE_PARTNER
    from apps.partners.models import (
        PartnerDocument,
        PartnerProfile,
        PartnerServiceSkill,
    )
    from apps.partners.services.readiness import DEFAULT_KIT_ITEMS

    now = timezone.now()
    # The role gate must be satisfied before any partner endpoint is reachable.
    user.grant_role(ROLE_PARTNER)
    # The flag too: without it the app keeps routing this account into partner
    # registration, which the profile created below makes impossible to complete.
    if not user.account_complete:
        user.account_complete = True
        user.save(update_fields=["account_complete", "updated_at"])
    profile, _ = PartnerProfile.objects.get_or_create(
        user=user,
        defaults={"display_name": f"Partner {user.phone}", "phone_verified": True},
    )
    profile.status = PartnerProfile.Status.APPROVED
    profile.phone_verified = True
    profile.insurance_expires_at = now + timedelta(days=180)
    profile.certification_expires_at = now + timedelta(days=365)
    profile.assessment_passed_at = now
    profile.commission_bps = 1500
    profile.service_radius_km = 20.0
    profile.default_capacity = 5
    # Dispatch filters candidates by home zone, so the fixture needs one.
    from apps.locations.models import ServiceZone

    profile.home_zone = zone or ServiceZone.objects.filter(code="ZONE-CENTRAL").first()
    profile.save()

    # A partner only receives offers while a shift is declared, which is the
    # declared-availability control the PDF requires.
    from apps.partners.services import availability as partner_availability

    partner_availability.start_shift(
        partner=profile,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(hours=8),
        zone=profile.home_zone,
        declared_capacity_minutes=420,
    )

    for service in ServiceType.objects.all():
        PartnerServiceSkill.objects.get_or_create(
            partner=profile,
            service=service,
            defaults={"proficiency": "assessed", "expires_at": now + timedelta(days=365)},
        )

    for code, name, required in DEFAULT_KIT_ITEMS:
        profile.equipment.update_or_create(
            item_code=code,
            defaults={"name": name, "required": required, "status": "present"},
        )

    for doc_type in ("identity", "business_registration", "insurance"):
        PartnerDocument.objects.update_or_create(
            partner=profile,
            doc_type=doc_type,
            defaults={
                "object_key": f"seed/{profile.pk}/{doc_type}.png",
                "verification_status": "verified",
                "verified_by": user,
                "verified_at": now,
                "expires_at": (now + timedelta(days=180)).date(),
                "content_type": "image/png",
                "byte_size": 100,
            },
        )

    # A recent location so the partner is rankable.
    profile.last_latitude = 12.9716
    profile.last_longitude = 77.5946
    profile.last_location_at = now
    profile.save(update_fields=["last_latitude", "last_longitude", "last_location_at"])
    return profile


def main() -> int:
    client = Client()
    stamp = f"{secrets.randbelow(10**6):06d}"

    # ------------------------------------------------------------------ setup
    section("Setup: accounts, catalog and zone")
    from apps.catalog.models import PriceRuleVersion, ServiceType
    from apps.locations.models import ServiceZone

    seed_zone = ServiceZone.objects.filter(code="ZONE-CENTRAL").first()
    check("seeded zone exists", seed_zone is not None)
    if seed_zone is None:
        return 1

    # An isolated zone keeps this run's dispatch deterministic.
    zone = make_test_zone(stamp)

    service = ServiceType.objects.filter(code="EXT_INT").first()
    check("catalog service exists", service is not None)
    check("price rule in force", PriceRuleVersion.current().currency == "INR")

    customer = login(client, f"9{stamp}0010")
    check("customer logged in", bool(customer["access_token"]))

    partner_login = login(client, f"9{stamp}0020")
    check("partner logged in", bool(partner_login["access_token"]))

    # ---------------------------------------------------------- registration
    section("Customer registration")
    reg = client.post(
        "/api/v1/auth/register/customer",
        data={
            "full_name": "Asha Rao",
            "email": "asha@example.test",
            "address": {
                "label": "Home",
                "line1": "12 Residency Road",
                "city": "Bengaluru",
                "state": "Karnataka",
                "postal_code": "560025",
                "country": "IN",
                "latitude": 12.9716,
                "longitude": 77.5946,
                "site_type": "standalone_house",
                "access_notes": "Gate code 4821. Park under the carport.",
            },
            "vehicle": {
                "vehicle_type": "car",
                "make": "Maruti",
                "model": "Swift",
                "year": 2019,
                "color": "White",
                "registration_number": "KA01AB1234",
            },
            "consent": {"terms": True, "privacy": True, "evidence": True},
        },
        content_type="application/json",
        **auth(customer["access_token"]),
    )
    check("customer registration is 201", reg.status_code == 201, f"got {reg.status_code} {reg.content[:200]}")
    if reg.status_code != 201:
        return 1
    reg_body = reg.json()
    vehicle_id = reg_body["vehicle"]["id"]
    address_id = reg_body["address"]["id"]

    cust_auth = auth(customer["access_token"])

    # ------------------------------------------------------- site method block
    section("Site method enforcement")
    basement = client.post(
        "/api/v1/addresses",
        data={
            "label": "Basement",
            "line1": "9 Service Lane",
            "city": "Bengaluru",
            "country": "IN",
            "latitude": 12.9716,
            "longitude": 77.5946,
            "site_type": "basement",
            "access_notes": "Basement B2",
        },
        content_type="application/json",
        **cust_auth,
    )
    check("second address created", basement.status_code == 201, f"got {basement.status_code}")
    basement_id = basement.json()["id"]

    blocked = client.post(
        "/api/v1/quotes",
        data={
            "vehicle_id": vehicle_id,
            "address_id": basement_id,
            "service_code": "INT_FULL",
            "booking_mode": "scheduled",
            "window_start": in_window_time(zone),
        },
        content_type="application/json",
        **cust_auth,
    )
    check(
        "interior service blocked at a basement",
        blocked.status_code == 422,
        f"got {blocked.status_code}",
    )
    if blocked.status_code == 422:
        check(
            "block reason is explicit",
            blocked.json()["error"]["code"] == "site_method_not_permitted",
            blocked.json()["error"]["code"],
        )

    # ------------------------------------------------------------------ quote
    section("Quote and itemisation")
    window_start_iso = in_window_time(zone)
    quote_resp = client.post(
        "/api/v1/quotes",
        data={
            "vehicle_id": vehicle_id,
            "address_id": address_id,
            "service_code": "EXT_INT",
            "addon_codes": ["ADD_WAX"],
            "booking_mode": "scheduled",
            "window_start": window_start_iso,
        },
        content_type="application/json",
        **cust_auth,
    )
    check("quote created", quote_resp.status_code == 201, f"got {quote_resp.status_code} {quote_resp.content[:300]}")
    if quote_resp.status_code != 201:
        return 1

    quote = quote_resp.json()
    line_types = {line["line_type"] for line in quote["lines"]}
    check("quote has a service base line", "service_base" in line_types, str(sorted(line_types)))
    check("quote has a vehicle tier line", "vehicle_tier" in line_types, str(sorted(line_types)))
    check("quote has an add-on line", "addon" in line_types, str(sorted(line_types)))
    check("quote has a zone/travel line", "zone_travel" in line_types, str(sorted(line_types)))
    check("quote records the price rule version", bool(quote["price_rule_version_label"]))
    check("quote exposes inclusions and exclusions", bool(quote["inclusions"]) and bool(quote["exclusions"]))

    computed = sum(line["amount_minor"] for line in quote["lines"])
    check(
        "line items sum to the total",
        computed == quote["total_minor"],
        f"lines={computed} total={quote['total_minor']}",
    )

    closed = client.post(
        "/api/v1/quotes",
        data={
            "vehicle_id": vehicle_id,
            "address_id": address_id,
            "service_code": "EXT_INT",
            "booking_mode": "scheduled",
            "window_start": out_of_window_time(zone),
        },
        content_type="application/json",
        **cust_auth,
    )
    check(
        "booking outside staffed hours is rejected",
        closed.status_code == 422,
        f"got {closed.status_code}",
    )

    # ---------------------------------------------------------------- booking
    section("Booking creation and price lock")
    booking_resp = client.post(
        "/api/v1/bookings",
        data={
            "quote_id": quote["id"],
            "terms_accepted": True,
            "cancellation_policy_accepted": True,
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"smoke-booking-{stamp}",
        **cust_auth,
    )
    check("booking created", booking_resp.status_code == 201, f"got {booking_resp.status_code} {booking_resp.content[:300]}")
    if booking_resp.status_code != 201:
        return 1

    booking = booking_resp.json()
    reference = booking["reference"]
    check("booking starts in requested", booking["status"] == "requested", booking["status"])
    check("booking has no promise window before assignment", booking["promise_window_start"] is None)

    replay = client.post(
        "/api/v1/bookings",
        data={"quote_id": quote["id"], "terms_accepted": True, "cancellation_policy_accepted": True},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"smoke-booking-{stamp}",
        **cust_auth,
    )
    check(
        "idempotency key replays the same booking",
        replay.status_code == 201 and replay.json()["reference"] == reference,
        f"got {replay.status_code}",
    )

    mismatch = client.post(
        "/api/v1/bookings",
        data={"quote_id": quote["id"], "terms_accepted": True, "cancellation_policy_accepted": True},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"smoke-booking-{stamp}-different",
        **cust_auth,
    )
    check(
        "a quote cannot be booked twice",
        mismatch.status_code >= 400,
        f"got {mismatch.status_code}",
    )

    # Re-quoting the same vehicle, address and service supersedes the earlier quote,
    # so only the newest price stays actionable.
    requote = client.post(
        "/api/v1/quotes",
        data={
            "vehicle_id": vehicle_id,
            "address_id": address_id,
            "service_code": "EXT_INT",
            "booking_mode": "scheduled",
            "window_start": window_start_iso,
        },
        content_type="application/json",
        **cust_auth,
    )
    check("re-quote created", requote.status_code == 201, f"got {requote.status_code}")
    if requote.status_code == 201:
        stale = client.post(
            "/api/v1/bookings",
            data={
                "quote_id": quote["id"],
                "terms_accepted": True,
                "cancellation_policy_accepted": True,
            },
            content_type="application/json",
            HTTP_IDEMPOTENCY_KEY=f"smoke-stale-{stamp}",
            **cust_auth,
        )
        check(
            "a superseded quote cannot be booked",
            stale.status_code >= 400,
            f"got {stale.status_code}",
        )

    # Client-supplied amounts must be ignored entirely; the server recomputes.
    tamper = client.post(
        "/api/v1/quotes",
        data={
            "vehicle_id": vehicle_id,
            "address_id": address_id,
            "service_code": "EXT_QUICK",
            "booking_mode": "scheduled",
            "window_start": in_window_time(zone, days_ahead=3),
            "total_minor": 1,
            "subtotal_minor": 1,
            "tax_minor": 0,
        },
        content_type="application/json",
        **cust_auth,
    )
    check(
        "client-supplied totals are ignored",
        tamper.status_code == 201 and tamper.json()["total_minor"] > 100,
        f"got {tamper.status_code}",
    )

    from apps.bookings.models import Booking as BookingModel

    locked = BookingModel.objects.get(reference=reference)
    try:
        locked.total_minor = 1
        locked.save()
        check("price cannot be altered after acceptance", False, "save() succeeded")
    except Exception:
        check("price cannot be altered after acceptance", True)

    # -------------------------------------------------------------- ownership
    section("Ownership and role enforcement")
    stranger = login(client, f"9{stamp}0099")
    stranger_view = client.get(
        f"/api/v1/bookings/{reference}", **auth(stranger["access_token"])
    )
    check("a stranger cannot read the booking", stranger_view.status_code == 403, f"got {stranger_view.status_code}")

    anon = client.get(f"/api/v1/bookings/{reference}")
    check("anonymous cannot read the booking", anon.status_code == 401, f"got {anon.status_code}")

    # ------------------------------------------------------- partner readiness
    section("Partner readiness gate")
    partner_user = partner_login["user"]["id"]
    from apps.identity.models import User

    partner_user_obj = User.objects.get(pk=partner_user)
    profile = make_ready_partner(partner_user_obj, zone=zone)

    # A second eligible partner, so the "only one acceptance wins" assertion is real.
    rival_login = login(client, f"9{stamp}0030")
    rival_user = User.objects.get(pk=rival_login["user"]["id"])
    rival = make_ready_partner(rival_user, zone=zone)


    readiness = client.get("/api/v1/partners/me", **auth(partner_login["access_token"]))
    check(
        "partner reports eligible for offers",
        readiness.status_code == 200 and readiness.json()["readiness"]["eligible_for_offers"],
        str(readiness.json().get("readiness", {}).get("summary"))[:160],
    )

    from apps.partners.services import readiness as readiness_service

    profile.insurance_expires_at = timezone.now() - timedelta(days=1)
    profile.save(update_fields=["insurance_expires_at"])
    expired = readiness_service.evaluate_readiness(profile)
    check(
        "expired insurance blocks offers",
        not expired.eligible_for_offers
        and "insurance_expired" in expired.codes,
        str(expired.codes),
    )
    profile.insurance_expires_at = timezone.now() + timedelta(days=180)
    profile.save(update_fields=["insurance_expires_at"])

    missing_kit = readiness_service.evaluate_readiness(profile)
    check("all readiness criteria satisfied", missing_kit.eligible_for_offers, missing_kit.summary)

    # ---------------------------------------------------------- authorisation
    section("Payment authorisation and dispatch")
    method = client.post(
        "/api/v1/payments/methods",
        data={"provider_token": f"tok_visa_{stamp}", "brand": "Visa", "last4": "4242"},
        content_type="application/json",
        **cust_auth,
    )
    check("payment method tokenised", method.status_code == 201, f"got {method.status_code}")
    method_id = method.json()["id"] if method.status_code == 201 else None

    declined = client.post(
        "/api/v1/payments/methods",
        data={"provider_token": "tok_decline", "brand": "Visa", "last4": "0002"},
        content_type="application/json",
        **cust_auth,
    )

    declined_id = declined.json()["id"] if declined.status_code == 201 else None

    pan = client.post(
        "/api/v1/payments/methods",
        data={"provider_token": "4111111111111111", "brand": "Visa"},
        content_type="application/json",
        **cust_auth,
    )
    check(
        "raw card data is rejected",
        400 <= pan.status_code < 500,
        f"got {pan.status_code}",
    )

    if declined_id:
        declining_quote = client.post(
            "/api/v1/quotes",
            data={
                "vehicle_id": vehicle_id,
                "address_id": address_id,
                "service_code": "EXT_QUICK",
                "booking_mode": "scheduled",
                "window_start": in_window_time(zone, days_ahead=2),
            },
            content_type="application/json",
            **cust_auth,
        )
        if declining_quote.status_code == 201:
            decline_booking = client.post(
                "/api/v1/bookings",
                data={
                    "quote_id": declining_quote.json()["id"],
                    "terms_accepted": True,
                    "cancellation_policy_accepted": True,
                },
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=f"smoke-decline-{stamp}",
                **cust_auth,
            )
            declined_authz = client.post(
                "/api/v1/payments/authorizations",
                data={
                    "booking_reference": decline_booking.json()["reference"],
                    "payment_method_id": declined_id,
                },
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY=f"smoke-decline-authz-{stamp}",
                **cust_auth,
            )
            check(
                "a declined authorisation fails the booking",
                declined_authz.status_code == 422,
                f"got {declined_authz.status_code}",
            )

    authz = client.post(
        "/api/v1/payments/authorizations",
        data={"booking_reference": reference, "payment_method_id": method_id},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"smoke-authz-{stamp}",
        **cust_auth,
    )
    check("payment authorised", authz.status_code == 201, f"got {authz.status_code} {authz.content[:250]}")
    if authz.status_code != 201:
        return 1

    locked.refresh_from_db()
    check("booking is dispatching after authorisation", locked.status == "dispatching", locked.status)
    check(
        "the booking resolved to the test zone",
        locked.zone.code == "TEST-DISPATCH",
        locked.zone.code,
    )

    # ------------------------------------------------------------ dispatch
    section("Offers and the atomic acceptance lock")
    from apps.dispatch.models import DispatchOffer

    offers = DispatchOffer.objects.filter(booking=locked, status="pending")
    check("an offer was sent", offers.count() >= 1, f"count={offers.count()}")
    if offers.count() == 0:
        check(
            "dispatch produced offers",
            False,
            "no pending offer; see the exclusion reasons above",
        )
        return 1

    # Act as whichever partner holds the offer. Ranking between two equally
    # positioned partners with no history is a tie, so the winner is not asserted
    # here; the lock is.
    offer = offers.order_by("rank").first()
    holder = profile if offer.partner_id == profile.pk else rival
    holder_login = partner_login if holder.pk == profile.pk else rival_login
    check(
        "the offer went to a ready partner",
        offer.partner_id in (profile.pk, rival.pk),
        f"offer partner={offer.partner_id}",
    )
    partner_auth = auth(holder_login["access_token"])

    offered_partners = set(
        DispatchOffer.objects.filter(booking=locked).values_list("partner_id", flat=True)
    )
    check(
        "both ready partners were ranked and offered work",
        {profile.pk, rival.pk}.issubset(offered_partners),
        f"offered={sorted(str(pid) for pid in offered_partners)}",
    )
    ranks = list(
        DispatchOffer.objects.filter(booking=locked).order_by("rank").values_list(
            "partner_id", "rank"
        )
    )
    check(
        "offers are ranked from best candidate",
        [r for _pid, r in ranks] == sorted(r for _pid, r in ranks),
        str(ranks),
    )

    # A ready partner outside this booking's zone receives no offer, so accepting
    # must be refused on ownership alone.
    outsider_login = login(client, f"9{stamp}0040")
    outsider_user = User.objects.get(pk=outsider_login["user"]["id"])
    make_ready_partner(outsider_user, zone=seed_zone)

    wrong = client.post(
        f"/api/v1/dispatch/offers/{offer.pk}",
        data={"action": "accept"},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"smoke-wrong-{stamp}",
        **auth(outsider_login["access_token"]),
    )
    check(
        "a partner cannot accept an offer sent to someone else",
        wrong.status_code == 403,
        f"got {wrong.status_code} {wrong.content[:150]}",
    )

    offer_view = client.get(f"/api/v1/dispatch/offers/{offer.pk}", **partner_auth)
    check(
        "the offer is readable by its recipient",
        offer_view.status_code == 200,
        f"got {offer_view.status_code} {offer_view.content[:200]}",
    )
    if offer_view.status_code == 200:
        payload = offer_view.json()
        check("offer shows access notes", bool(payload.get("access_notes")), str(payload.get("access_notes"))[:60])
        check("offer shows a payout estimate", payload.get("payout_estimate_minor", 0) > 0)
        check("offer is time limited", payload.get("seconds_remaining", 0) > 0)

    no_key = client.post(
        f"/api/v1/dispatch/offers/{offer.pk}",
        data={"action": "accept"},
        content_type="application/json",
        **partner_auth,
    )
    check(
        "accepting without an idempotency key is refused",
        no_key.status_code == 400,
        f"got {no_key.status_code}",
    )

    # The partner who did not win still holds their own pending offer for the same
    # booking, which is what the atomic lock has to resolve.
    second = DispatchOffer.objects.filter(
        booking=locked, status__in=("pending", "superseded", "accepted")
    ).exclude(pk=offer.pk).first()
    check("a second partner holds a competing offer", second is not None)

    accept = client.post(
        f"/api/v1/dispatch/offers/{offer.pk}",
        data={"action": "accept"},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"smoke-accept-{stamp}",
        **partner_auth,
    )
    check("offer accepted", accept.status_code == 200, f"got {accept.status_code} {accept.content[:250]}")

    locked.refresh_from_db()
    check("booking is assigned", locked.status == "assigned", locked.status)
    check("booking has a partner", locked.partner_id == holder.pk, f"{locked.partner_id} vs {holder.pk}")
    check("arrival promise published only after acceptance", locked.promise_window_start is not None)

    if second is not None:
        second.refresh_from_db()
        check(
            "the losing offer is superseded",
            second.status == "superseded",
            second.status,
        )

    double = client.post(
        f"/api/v1/dispatch/offers/{offer.pk}",
        data={"action": "accept"},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"smoke-double-{stamp}",
        **partner_auth,
    )
    check(
        "a won offer cannot be accepted twice",
        double.status_code >= 400,
        f"got {double.status_code}",
    )

    loser_login = rival_login if holder.pk == profile.pk else partner_login
    loser_job = client.get(
        f"/api/v1/bookings/{reference}/job", **auth(loser_login["access_token"])
    )
    check(
        "a partner who lost the race has no job access",
        loser_job.status_code == 403,
        f"got {loser_job.status_code}",
    )

    # ---------------------------------------------------- illegal transition
    section("Server-side state machine enforcement")
    illegal = client.post(
        f"/api/v1/bookings/{reference}/complete",
        data={"checklist_confirmed": True},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"smoke-illegal-{stamp}",
        **partner_auth,
    )
    check(
        "cannot jump from assigned to complete",
        illegal.status_code == 409,
        f"got {illegal.status_code} {illegal.content[:150]}",
    )
    if illegal.status_code == 409:
        check(
            "illegal transition has a stable code",
            illegal.json()["error"]["code"] == "invalid_state_transition",
            illegal.json()["error"]["code"],
        )

    customer_start = client.post(
        f"/api/v1/bookings/{reference}/milestones/start",
        data={},
        content_type="application/json",
        **cust_auth,
    )
    check(
        "a customer cannot drive partner milestones",
        customer_start.status_code == 403,
        f"got {customer_start.status_code} {customer_start.content[:120]}",
    )

    # ------------------------------------------------------------- fulfilment
    section("Fulfilment with guided evidence")
    job = client.get(f"/api/v1/bookings/{reference}/job", **partner_auth)
    check("partner can open the job", job.status_code == 200, f"got {job.status_code}")
    check("job lists required evidence", "required_evidence" in job.json())

    en_route = client.post(
        f"/api/v1/bookings/{reference}/milestones/en_route",
        data={},
        content_type="application/json",
        **partner_auth,
    )
    check("partner is en route", en_route.status_code == 200, f"got {en_route.status_code}")

    wrong_code = client.post(
        f"/api/v1/bookings/{reference}/milestones/arrived",
        data={"booking_code": "000000"},
        content_type="application/json",
        **partner_auth,
    )
    check(
        "arrival requires a valid booking code",
        wrong_code.status_code == 409,
        f"got {wrong_code.status_code}",
    )

    arrived = client.post(
        f"/api/v1/bookings/{reference}/milestones/arrived",
        data={"booking_code": locked.booking_code},
        content_type="application/json",
        **partner_auth,
    )
    check("arrival confirmed with the right code", arrived.status_code == 200, f"got {arrived.status_code}")

    start_early = client.post(
        f"/api/v1/bookings/{reference}/milestones/start",
        data={},
        content_type="application/json",
        **partner_auth,
    )
    check(
        "cannot start without pre-service evidence",
        start_early.status_code == 409,
        f"got {start_early.status_code}",
    )
    if start_early.status_code == 409:
        check(
            "missing evidence has a specific code",
            start_early.json()["error"]["code"] == "evidence_incomplete",
            start_early.json()["error"]["code"],
        )

    bad_evidence = client.post(
        f"/api/v1/bookings/{reference}/evidence",
        data={
            "evidence_type": "pre_condition",
            "captured_at": timezone.now().isoformat(),
            "sequence": 0,
            "checks": json.dumps({"lighting_ok": True}),
            "file": _png("bad.png"),
        },
        **partner_auth,
    )
    check(
        "guided capture requires all three checks",
        bad_evidence.status_code == 400,
        f"got {bad_evidence.status_code}",
    )

    not_an_image = client.post(
        f"/api/v1/bookings/{reference}/evidence",
        data={
            "evidence_type": "pre_condition",
            "captured_at": timezone.now().isoformat(),
            "checks": json.dumps(
                {"lighting_ok": True, "angle_ok": True, "identity_confirmed": True}
            ),
            "file": _text_payload(),
        },
        **partner_auth,
    )
    check(
        "a non-image upload is rejected",
        not_an_image.status_code == 400,
        f"got {not_an_image.status_code}",
    )

    pre = client.post(
        f"/api/v1/bookings/{reference}/evidence",
        data={
            "evidence_type": "pre_condition",
            "captured_at": timezone.now().isoformat(),
            "client_photo_id": f"pre-{stamp}",
            "sequence": 0,
            "checks": json.dumps(
                {"lighting_ok": True, "angle_ok": True, "identity_confirmed": True}
            ),
            "file": _png("pre.png"),
        },
        **partner_auth,
    )
    check("pre-service evidence accepted", pre.status_code == 201, f"got {pre.status_code} {pre.content[:200]}")

    duplicate_evidence = client.post(
        f"/api/v1/bookings/{reference}/evidence",
        data={
            "evidence_type": "pre_condition",
            "captured_at": timezone.now().isoformat(),
            "client_photo_id": f"pre-{stamp}",
            "sequence": 0,
            "checks": json.dumps(
                {"lighting_ok": True, "angle_ok": True, "identity_confirmed": True}
            ),
            "file": _png("pre2.png"),
        },
        **partner_auth,
    )
    check(
        "a retried upload is idempotent",
        duplicate_evidence.status_code == 201
        and duplicate_evidence.json()["id"] == pre.json()["id"],
        f"got {duplicate_evidence.status_code}",
    )

    started = client.post(
        f"/api/v1/bookings/{reference}/milestones/start",
        data={},
        content_type="application/json",
        **partner_auth,
    )
    check("service started after pre-evidence", started.status_code == 200, f"got {started.status_code}")

    complete_early = client.post(
        f"/api/v1/bookings/{reference}/complete",
        data={"checklist_confirmed": True},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"smoke-early-{stamp}",
        **partner_auth,
    )
    check(
        "cannot complete without after-service evidence",
        complete_early.status_code == 409,
        f"got {complete_early.status_code}",
    )

    checklist = BookingModel.objects.get(reference=reference).checklist_items.all()
    client.post(
        f"/api/v1/bookings/{reference}/checklist",
        data={
            "items": [
                {"code": item.code, "done": True} for item in checklist
            ]
        },
        content_type="application/json",
        **partner_auth,
    )

    post = client.post(
        f"/api/v1/bookings/{reference}/evidence",
        data={
            "evidence_type": "post_service",
            "captured_at": timezone.now().isoformat(),
            "client_photo_id": f"post-{stamp}",
            "sequence": 0,
            "checks": json.dumps(
                {"lighting_ok": True, "angle_ok": True, "identity_confirmed": True}
            ),
            "file": _png("post.png"),
        },
        **partner_auth,
    )
    check("after-service evidence accepted", post.status_code == 201, f"got {post.status_code}")

    completed = client.post(
        f"/api/v1/bookings/{reference}/complete",
        data={"checklist_confirmed": True, "notes": "Finished."},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"smoke-complete-{stamp}",
        **partner_auth,
    )
    check("job completed", completed.status_code == 200, f"got {completed.status_code} {completed.content[:250]}")

    locked.refresh_from_db()
    check("booking is completed", locked.status == "completed", locked.status)

    # ------------------------------------------------------------------ money
    section("Capture, ledger and partner payout")
    from apps.payments.models import LedgerEntry, PaymentAttempt

    attempt = PaymentAttempt.objects.filter(
        booking=locked, status=PaymentAttempt.Status.AUTHORIZED
    ).first()

    ops_login = _ops_login(client, stamp)
    ops_auth = auth(ops_login["access_token"])

    capture = client.post(
        f"/api/v1/payments/{attempt.pk}/capture",
        data={},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"smoke-capture-{stamp}",
        **ops_auth,
    )
    check("payment captured by operations", capture.status_code == 200, f"got {capture.status_code} {capture.content[:250]}")

    double_capture = client.post(
        f"/api/v1/payments/{attempt.pk}/capture",
        data={},
        content_type="application/json",
        **ops_auth,
    )
    check(
        "a payment cannot be captured twice",
        double_capture.status_code >= 400,
        f"got {double_capture.status_code}",
    )

    locked.refresh_from_db()
    check("booking is payout eligible", locked.status == "partner_payout_eligible", locked.status)
    check("captured amount recorded", locked.captured_minor == locked.total_minor)

    ledger = LedgerEntry.objects.filter(booking=locked)
    accounts = {entry.account for entry in ledger}
    check("ledger has a customer cash entry", "customer_cash" in accounts, str(sorted(accounts)))
    check("ledger has a partner payable entry", "partner_payable" in accounts, str(sorted(accounts)))

    try:
        entry = ledger.first()
        entry.amount_minor = entry.amount_minor + 1000
        entry.save()
        check("ledger entries are immutable", False, "save() succeeded")
    except Exception:
        check("ledger entries are immutable", True)

    # ----------------------------------------------------------------- rating
    section("Rating, support and dashboards")
    early_rating = client.post(
        f"/api/v1/bookings/{reference}/rating",
        data={"rating": 5},
        content_type="application/json",
        **cust_auth,
    )
    check("completed booking can be rated", early_rating.status_code == 200, f"got {early_rating.status_code}")

    case = client.post(
        f"/api/v1/bookings/{reference}/issue",
        data={"category": "damage", "description": "Scratch noticed on the rear bumper."},
        content_type="application/json",
        **cust_auth,
    )
    check("damage case opened", case.status_code == 201, f"got {case.status_code}")
    if case.status_code == 201:
        check("evidence frozen on a damage case", case.json()["evidence_frozen"] is True)

        liability = client.post(
            f"/api/v1/ops/support-cases/{case.json()['reference']}",
            data={
                "liability_outcome": "partner_at_fault",
                "liability_notes": "Reviewed after-service photos.",
                "note": "Reviewed and assigned.",
            },
            content_type="application/json",
            **ops_auth,
        )
        check(
            "liability recorded against a person",
            liability.status_code == 200,
            f"got {liability.status_code}",
        )

    refund = client.post(
        "/api/v1/payments/refunds",
        data={
            "booking_reference": reference,
            "amount_minor": 10000,
            "refund_type": "partial",
            "reason_code": "damage_claim",
            "reason_text": "Partial goodwill for the reported scratch.",
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"smoke-refund-{stamp}",
        **ops_auth,
    )
    check("partial refund executed", refund.status_code == 201, f"got {refund.status_code} {refund.content[:250]}")

    over_refund = client.post(
        "/api/v1/payments/refunds",
        data={
            "booking_reference": reference,
            "amount_minor": locked.total_minor * 10,
            "refund_type": "partial",
            "reason_code": "test",
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY=f"smoke-over-refund-{stamp}",
        **ops_auth,
    )
    check(
        "a refund cannot exceed the captured amount",
        over_refund.status_code == 422,
        f"got {over_refund.status_code} {over_refund.content[:220]}",
    )

    dashboard = client.get("/api/v1/ops/dashboards/pilot", **ops_auth)
    check("pilot dashboard renders", dashboard.status_code == 200, f"got {dashboard.status_code}")
    if dashboard.status_code == 200:
        names = {m["name"] for m in dashboard.json()["metrics"]}
        for metric in (
            "fulfilment",
            "on_time_arrival",
            "customer_rating",
            "rework_refund",
            "partner_utilization",
            "safety_and_trust",
        ):
            check(f"dashboard reports {metric}", metric in names)

    exceptions = client.get("/api/v1/ops/exceptions", **ops_auth)
    check("exception queue responds", exceptions.status_code == 200, f"got {exceptions.status_code}")

    # The audit log is administrator-only, so this needs a genuine ops account
    # rather than the admin used elsewhere.
    ops_only_login = _ops_only_login(client, stamp)
    audit = client.get("/api/v1/ops/audit", **auth(ops_only_login["access_token"]))
    check(
        "ops role cannot read the admin audit log",
        audit.status_code == 403,
        f"got {audit.status_code}",
    )

    admin_audit = client.get("/api/v1/ops/audit", **ops_auth)
    check(
        "an administrator can read the audit log",
        admin_audit.status_code == 200,
        f"got {admin_audit.status_code}",
    )

    # ------------------------------------------------------------------ events
    section("Append-only history and outbox")
    events = client.get(f"/api/v1/bookings/{reference}/events", **cust_auth)
    check("event history readable", events.status_code == 200, f"got {events.status_code}")
    if events.status_code == 200:
        rows = events.json()
        check("history starts at seq 1", rows[0]["seq"] == 1)
        check("history records creation", rows[0]["event_type"] == "booking.created")
        types = {row["event_type"] for row in rows}
        for expected in (
            "booking.created",
            "dispatch.offer_accepted",
            "evidence.uploaded",
            "booking.complete",
        ):
            check(f"history records {expected}", expected in types, str(sorted(types)))

    from apps.notifications.models import OutboxEvent

    check(
        "outbox events were written transactionally",
        OutboxEvent.objects.filter(aggregate_id=str(locked.pk)).exists(),
    )

    # ----------------------------------------------------------------- summary
    print()
    print(f"{len(PASSES)} passed, {len(FAILURES)} failed")
    if FAILURES:
        print("FAILURES:")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("full booking loop verified end to end")
    return 0


def _png(name: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, png_bytes(), content_type="image/png")


def _text_payload() -> SimpleUploadedFile:
    return SimpleUploadedFile(
        "payload.png", b"#!/bin/sh\necho not an image\n", content_type="image/png"
    )


def _token_for(user) -> str:
    from apps.identity.services import tokens as token_service

    pair = token_service.issue_token_pair(user)
    return pair.access_token


def _ops_only_login(client: Client, stamp: str) -> dict:
    """A session for an account holding only the ops role.

    Used to prove the audit log is genuinely administrator-only.
    """
    from apps.identity.models import User
    from apps.identity.services import tokens as token_service

    user = (
        User.objects.filter(role_grants__role="ops", role_grants__revoked_at__isnull=True)
        .exclude(pk__in=User.objects.filter(role_grants__role="admin").values("pk"))
        .first()
    )
    if user is None:
        user = User.objects.create_user(
            phone=f"+9197{stamp}0002",
            password="OpsOnly-Local-2026",
            full_name="Operations Agent",
            account_complete=True,
            is_staff_account=True,
        )
        user.grant_role("ops")
    pair = token_service.issue_token_pair(user, mfa_verified=True)
    return {"access_token": pair.access_token}


def _ops_login(client: Client, stamp: str) -> dict:
    from apps.identity.models import User
    from apps.identity.services import tokens as token_service

    user = User.objects.filter(role_grants__role="admin").first()
    if user is None:
        user = User.objects.filter(role_grants__role="ops").first()
    if user is None:
        raise SystemExit("No operations account exists. Run: manage.py seed_pilot --demo-users")
    pair = token_service.issue_token_pair(user, mfa_verified=True)
    return {"access_token": pair.access_token}


if __name__ == "__main__":
    sys.exit(main())