"""Account registration.

Registration happens *after* a verified OTP login, so the phone is already proven.
Two flows exist:

``register_customer``
    Profile, a first service address (with a map pin, site type and access notes)
    and a first vehicle. This mirrors the "choose: add a vehicle, select a supported
    service and location" step of the customer journey.

``register_partner``
    A partner application. This creates a ``pending_verification`` profile. It does
    **not** make the partner eligible for offers: verification, insurance validity,
    kit completeness and a practical assessment are all still required, which is the
    PDF's partner-readiness gate.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from apps.common.exceptions import Conflict, PermissionDenied
from apps.identity.models import ROLE_CUSTOMER, ROLE_PARTNER, User
from apps.identity.services.consents import current_version, record_consents


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    user: User
    created: bool
    extra: dict


class AlreadyRegistered(Conflict):
    code = "already_registered"
    default_message = "This account has already been registered."


class RegistrationNotAllowed(PermissionDenied):
    code = "registration_not_allowed"
    default_message = "This account cannot be registered this way."


def _lock_account(user: User) -> None:
    """Serialise registration for one account and re-read its registration flag.

    Two submissions of the same form (a double tap, an app retry) would otherwise
    both pass the guards below, and the partner flow would collide on the
    one-to-one profile. Locking the account row makes the second submission wait,
    then observe the flag the first one committed. Must be called inside the
    ``atomic`` block that performs the registration.
    """
    User.objects.select_for_update().filter(pk=user.pk).exists()
    user.refresh_from_db(fields=["account_complete"])


@transaction.atomic
def register_customer(*, user: User, payload: dict, request=None) -> RegistrationResult:
    """Complete a customer account: profile, address, vehicle, consent."""
    from apps.catalog.models import Vehicle
    from apps.locations.models import Address

    _lock_account(user)

    if user.account_complete:
        raise AlreadyRegistered

    roles = set(user.roles())
    if roles & {"ops", "admin"}:
        raise RegistrationNotAllowed("Staff accounts do not register as customers.")

    user.full_name = payload["full_name"].strip()
    if payload.get("email"):
        user.email = payload["email"].strip().lower()
    user.account_complete = True
    user.save(update_fields=["full_name", "email", "account_complete", "updated_at"])

    user.grant_role(ROLE_CUSTOMER)

    address = Address.objects.create(
        owner=user,
        label=payload["address"].get("label") or "Home",
        line1=payload["address"]["line1"].strip(),
        line2=(payload["address"].get("line2") or "").strip(),
        city=payload["address"]["city"].strip(),
        state=payload["address"].get("state", "").strip(),
        postal_code=payload["address"].get("postal_code", "").strip(),
        country=payload["address"].get("country") or "India",
        latitude=payload["address"]["latitude"],
        longitude=payload["address"]["longitude"],
        site_type=payload["address"]["site_type"],
        access_notes=(payload["address"].get("access_notes") or "").strip(),
        parking_details=(payload["address"].get("parking_details") or "").strip(),
        property_approval=bool(payload["address"].get("property_approval", False)),
        is_default=True,
    )

    vehicle_data = payload["vehicle"]
    vehicle = Vehicle.objects.create(
        owner=user,
        vehicle_type=vehicle_data["vehicle_type"],
        make=vehicle_data["make"].strip(),
        model=vehicle_data["model"].strip(),
        year=vehicle_data.get("year"),
        color=(vehicle_data.get("color") or "").strip(),
        registration_number=(vehicle_data.get("registration_number") or "").strip().upper(),
        is_default=True,
    )

    record_consents(user, payload.get("consent") or {}, request=request)

    return RegistrationResult(
        user=user, created=True, extra={"address": address, "vehicle": vehicle}
    )


@transaction.atomic
def register_partner(*, user: User, payload: dict, request=None) -> RegistrationResult:
    """Create a partner application in ``pending_verification``."""
    from apps.catalog.models import ServiceType
    from apps.partners.models import (
        PartnerEquipmentItem,
        PartnerProfile,
        PartnerServiceSkill,
    )
    from apps.partners.services.readiness import DEFAULT_KIT_ITEMS

    _lock_account(user)

    if user.account_complete:
        raise AlreadyRegistered

    # A profile can exist while the flag is false - a partner fixture, or an
    # application written outside this service - and the one-to-one on
    # PartnerProfile makes that a hard failure rather than a second application.
    if PartnerProfile.objects.filter(user=user).exists():
        raise AlreadyRegistered

    roles = set(user.roles())
    if roles & {"ops", "admin"}:
        raise RegistrationNotAllowed("Staff accounts do not register as partners.")

    profile = PartnerProfile.objects.create(
        user=user,
        display_name=payload["display_name"].strip(),
        bio=(payload.get("bio") or "").strip(),
        payout_account_ref=(payload.get("payout_account_ref") or "").strip(),
        payout_provider=payload.get("payout_provider") or "sandbox",
    )
    user.grant_role(ROLE_PARTNER)

    if not user.full_name:
        user.full_name = payload["display_name"].strip()

    # Declared skills. Unknown service codes are rejected by the serializer, so an
    # unverified skill can never reach the eligibility filter.
    declared = set(payload.get("skills") or [])
    for service in ServiceType.objects.filter(code__in=declared, is_active=True):
        PartnerServiceSkill.objects.create(
            partner=profile,
            service=service,
            proficiency=PartnerServiceSkill.Proficiency.TRAINED,
        )

    # Kit checklist is pre-seeded as "missing" so the partner works through it; the
    # readiness gate stays closed until every required item is present.
    submitted_equipment = {
        str(item.get("item_code")): item for item in (payload.get("equipment") or [])
    }
    for code, name, required in DEFAULT_KIT_ITEMS:
        supplied = submitted_equipment.get(code)
        PartnerEquipmentItem.objects.create(
            partner=profile,
            item_code=code,
            name=name,
            required=required,
            status=(
                PartnerEquipmentItem.Status.PRESENT
                if supplied and supplied.get("status") == "present"
                else PartnerEquipmentItem.Status.MISSING
            ),
        )

    record_consents(user, payload.get("consent") or {}, request=request)

    # Account completion for a partner means the *application* is submitted; the
    # profile remains pending_verification until operations approves it.
    user.account_complete = True
    user.save(update_fields=["account_complete", "full_name", "updated_at"])

    return RegistrationResult(user=user, created=True, extra={"partner": profile})


def complete_customer_registration(result: RegistrationResult) -> dict:
    from apps.catalog.serializers import VehicleSerializer
    from apps.locations.serializers import AddressSerializer

    return {
        "user_id": str(result.user.pk),
        "address": AddressSerializer(result.extra["address"]).data,
        "vehicle": VehicleSerializer(result.extra["vehicle"]).data,
        "consent_version": current_version(),
    }


def complete_partner_registration(result: RegistrationResult) -> dict:
    from apps.partners.serializers import PartnerProfileSerializer

    return {
        "user_id": str(result.user.pk),
        "partner": PartnerProfileSerializer(result.extra["partner"]).data,
        "next": "awaiting_verification",
    }


__all__ = [
    "AlreadyRegistered",
    "RegistrationNotAllowed",
    "RegistrationResult",
    "register_customer",
    "register_partner",
    "complete_customer_registration",
    "complete_partner_registration",
]