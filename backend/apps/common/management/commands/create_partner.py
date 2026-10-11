"""Create or refresh a partner that is approved and ready to receive offers.

An approved partner profile is only half of the story: the readiness gate in
:mod:`apps.partners.services.readiness` also demands a verified identity document,
valid insurance, live certification, a passed practical assessment, the full kit and
- per booking - a current skill for the service being offered. Dispatch additionally
excludes a partner who is off shift or whose position is stale. This command fills
every one of those inputs in one transaction so a partner created for testing or for
a pilot go-live can actually receive an offer immediately.

Idempotent: re-running updates the existing account instead of failing.

    python manage.py create_partner --name "Aqua Cleaners" --phone 7588528702 \
        --lat 18.5196 --lng 73.8557
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import ServiceType
from apps.common.exceptions import LocationUpdateStale
from apps.identity.models import ROLE_CUSTOMER, ROLE_PARTNER, STAFF_ROLES, User, normalise_phone
from apps.locations.models import ServiceZone
from apps.partners.models import (
    PartnerDocument,
    PartnerEquipmentItem,
    PartnerProfile,
    PartnerServiceSkill,
)
from apps.partners.services import availability as partner_availability
from apps.partners.services import location_ingest
from apps.partners.services.readiness import (
    DEFAULT_KIT_ITEMS,
    REQUIRED_DOCUMENT_TYPES,
    evaluate_readiness,
)

DEFAULT_ZONE_CODE = "ZONE-CENTRAL"
DEFAULT_COMMISSION_BPS = 1500
DEFAULT_RADIUS_KM = 20.0
DEFAULT_CAPACITY = 4
DEFAULT_SHIFT_HOURS = 12


class Command(BaseCommand):
    help = "Create an approved, offer-ready partner account."

    def add_arguments(self, parser):
        parser.add_argument("--phone", required=True, help="Contact number; a bare 10-digit number becomes +91.")
        parser.add_argument("--name", required=True, help="Business display name.")
        parser.add_argument("--zone", default=DEFAULT_ZONE_CODE, help="Service zone code (home zone).")
        parser.add_argument("--lat", type=float, required=True, help="Base latitude.")
        parser.add_argument("--lng", type=float, required=True, help="Base longitude.")
        parser.add_argument("--bio", default="", help="Public business description.")
        parser.add_argument("--address", default="", help="Human-readable base address, recorded in the bio line.")
        parser.add_argument("--commission-bps", type=int, default=DEFAULT_COMMISSION_BPS, help="Platform commission in basis points.")
        parser.add_argument("--radius-km", type=float, default=DEFAULT_RADIUS_KM, help="Declared travel radius.")
        parser.add_argument("--capacity", type=int, default=DEFAULT_CAPACITY, help="Concurrent job capacity.")
        parser.add_argument("--shift-hours", type=int, default=DEFAULT_SHIFT_HOURS, help="Length of the shift to declare.")
        parser.add_argument("--payout-ref", default="", help="Payout provider token. Never a bank account number.")
        parser.add_argument(
            "--revoke-customer",
            action="store_true",
            help="Leave the account partner-only, dropping a pre-existing customer role.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        zone = self._zone(options["zone"])
        actor = self._actor()

        user = self._account(options)
        profile = self._profile(user=user, zone=zone, options=options, actor=actor)
        self._documents(profile=profile, actor=actor)
        self._kit(profile=profile, actor=actor)
        self._skills(profile=profile)
        self._shift(profile=profile, zone=zone, hours=options["shift_hours"])
        self._position(profile=profile, options=options)

        readiness = evaluate_readiness(profile)
        self.stdout.write(f"partner   {profile.display_name} <{user.phone}> id={profile.pk}")
        self.stdout.write(f"home zone {zone.code} ({zone.name})")
        self.stdout.write(f"on shift  {partner_availability.is_on_shift(profile)}")
        if readiness.eligible_for_offers:
            self.stdout.write(self.style.SUCCESS("readiness  ready to receive offers"))
        else:
            # Raising rolls the transaction back, so a partner is never left behind
            # in a state the gate will not actually honour.
            raise CommandError(
                "partner is still blocked from offers: "
                + "; ".join(f"{b.code} ({b.message})" for b in readiness.blockers)
            )

    # ------------------------------------------------------------------ helpers

    def _zone(self, code: str) -> ServiceZone:
        zone = ServiceZone.objects.filter(code=code).first()
        if zone is None:
            raise CommandError(f"Unknown service zone {code!r}. Run: manage.py seed_pilot")
        if not zone.is_active:
            raise CommandError(f"Service zone {code!r} is inactive, so no booking would ever dispatch to it.")
        return zone

    def _actor(self) -> User | None:
        """An operations account, so the approval carries a real audit trail."""
        return (
            User.objects.filter(role_grants__role__in=STAFF_ROLES, role_grants__revoked_at__isnull=True)
            .order_by("created_at")
            .first()
        )

    def _account(self, options) -> User:
        phone = normalise_phone(options["phone"])
        user = User.objects.filter(phone=phone).first()
        if user is None:
            user = User.objects.create_user(phone=phone, full_name=options["name"])
            self.stdout.write(f"created account {phone}")
        else:
            self.stdout.write(f"reusing account {phone}")

        # ``account_complete`` is what stops the app sending the account back into
        # the registration flow; a partner profile without it is a dead end.
        user.full_name = options["name"]
        user.account_complete = True
        user.phone_verified_at = user.phone_verified_at or timezone.now()
        user.save(update_fields=["full_name", "account_complete", "phone_verified_at", "updated_at"])
        user.grant_role(ROLE_PARTNER)
        if options["revoke_customer"] and ROLE_CUSTOMER in user.roles():
            # Revoked, not deleted: the grant history stays auditable.
            user.revoke_role(ROLE_CUSTOMER)
            self.stdout.write("revoked the customer role; this account washes cars, it does not book them")
        return user

    def _profile(self, *, user: User, zone: ServiceZone, options, actor) -> PartnerProfile:
        profile, _ = PartnerProfile.objects.get_or_create(
            user=user, defaults={"display_name": options["name"], "bio": options["bio"]}
        )
        profile.display_name = options["name"]
        profile.bio = "\n".join(part for part in (options["bio"], options["address"]) if part)
        profile.payout_provider = profile.payout_provider or "sandbox"
        profile.payout_account_ref = options["payout_ref"]
        profile.home_zone = zone
        profile.commission_bps = options["commission_bps"]
        profile.service_radius_km = options["radius_km"]
        profile.default_capacity = options["capacity"]
        profile.phone_verified = True
        profile.insurance_expires_at = timezone.now() + timedelta(days=365)
        profile.insurance_renewal_owner = options["name"]
        profile.certification_expires_at = timezone.now() + timedelta(days=365)
        profile.certification_renewal_owner = options["name"]
        profile.assessment_passed_at = timezone.now()
        profile.assessment_notes = "Practical assessment recorded at onboarding."
        profile.save()
        profile.approve(by=actor)
        return profile

    def _documents(self, *, profile: PartnerProfile, actor) -> None:
        """Verified evidence. The gate reads these, not the profile flags."""
        now = timezone.now()
        for doc_type in REQUIRED_DOCUMENT_TYPES:
            document, _ = PartnerDocument.objects.get_or_create(
                partner=profile,
                doc_type=doc_type,
                defaults={
                    # Deterministic key so a re-run updates this row instead of
                    # colliding on the unique constraint.
                    "object_key": f"partners/{profile.pk}/{doc_type}.pdf",
                    "content_type": "application/pdf",
                    "byte_size": 1,
                },
            )
            document.issued_at = now.date() - timedelta(days=30)
            document.expires_at = now.date() + timedelta(days=365)
            document.verification_status = PartnerDocument.VerificationStatus.VERIFIED
            document.verified_by = actor
            document.verified_at = now
            document.rejection_reason = ""
            document.save()

    def _kit(self, *, profile: PartnerProfile, actor) -> None:
        now = timezone.now()
        for code, name, required in DEFAULT_KIT_ITEMS:
            item, _ = PartnerEquipmentItem.objects.get_or_create(
                partner=profile,
                item_code=code,
                defaults={"name": name, "required": required},
            )
            item.name = name
            item.required = required
            item.status = PartnerEquipmentItem.Status.PRESENT
            item.checked_at = now
            item.checked_by = actor
            item.notes = ""
            item.save()

    def _skills(self, *, profile: PartnerProfile) -> None:
        """Assess every active service, so no booking can be blocked on skill."""
        now = timezone.now()
        for service in ServiceType.objects.filter(is_active=True):
            PartnerServiceSkill.objects.update_or_create(
                partner=profile,
                service=service,
                defaults={
                    "proficiency": PartnerServiceSkill.Proficiency.ASSESSED,
                    "certified_at": now,
                    "expires_at": now + timedelta(days=365),
                },
            )

    def _shift(self, *, profile: PartnerProfile, zone: ServiceZone, hours: int) -> None:
        """A declared shift. Dispatch will not offer work to an off-shift partner."""
        now = timezone.now()
        partner_availability.end_shift(partner=profile, at=now)
        partner_availability.start_shift(
            partner=profile,
            starts_at=now,
            ends_at=now + timedelta(hours=hours),
            zone=zone,
            declared_capacity_minutes=hours * 60,
        )

    def _position(self, *, profile: PartnerProfile, options) -> None:
        """Seed the tracked position through the privacy-gated ingest path."""
        try:
            location_ingest.record_location(
                partner=profile,
                latitude=options["lat"],
                longitude=options["lng"],
                recorded_at=timezone.now(),
                accuracy_m=25.0,
            )
        except LocationUpdateStale:
            self.stdout.write("kept the existing position (a newer ping is already on file)")