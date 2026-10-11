"""Partner readiness: the single gate that decides offer eligibility.

The PDF is explicit: *"Suspend new offers when certification, required kit or
insurance status expires"*, and a short observed practical assessment is required
before activation. Every eligibility decision resolves through
:func:`evaluate_readiness`, so no view can accidentally bypass the gate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.utils import timezone

from apps.partners.models import PartnerProfile

logger = logging.getLogger("apps.partners.readiness")


class BlockerCode:
    NOT_APPROVED = "partner_not_approved"
    SUSPENDED = "partner_suspended"
    PHONE_UNVERIFIED = "phone_not_verified"
    IDENTITY_NOT_VERIFIED = "identity_document_unverified"
    INSURANCE_MISSING = "insurance_missing"
    INSURANCE_EXPIRED = "insurance_expired"
    KIT_INCOMPLETE = "kit_incomplete"
    KIT_EXPIRED = "kit_expired"
    ASSESSMENT_MISSING = "practical_assessment_missing"
    SKILL_MISSING = "skill_missing"


#: Documents that must be verified before a partner may take work.
REQUIRED_DOCUMENT_TYPES: tuple[str, ...] = (
    "identity",
    "business_registration",
    "insurance",
)


@dataclass(frozen=True, slots=True)
class ReadinessBlocker:
    code: str
    message: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Readiness:
    """The outcome of a readiness evaluation."""

    eligible_for_offers: bool
    blockers: list[ReadinessBlocker] = field(default_factory=list)

    @property
    def codes(self) -> list[str]:
        return [blocker.code for blocker in self.blockers]

    @property
    def summary(self) -> str:
        if self.eligible_for_offers:
            return "Ready to receive offers"
        return "; ".join(blocker.message for blocker in self.blockers)


#: The standardised kit the PDF requires to be issued or inspected.
#: (code, display name, required)
DEFAULT_KIT_ITEMS: tuple[tuple[str, str, bool], ...] = (
    ("approved_cleaner", "Approved cleaner with current safety data sheet", True),
    ("clean_towels", "Separated, clean towel set", True),
    ("ppe", "Personal protective equipment", True),
    ("power_water_unit", "Safe power and water equipment", True),
    ("waste_containment", "Waste containment kit", True),
    ("water_source", "Water supply arrangement", True),
    ("replenishment", "Replenishment checklist", False),
)


def evaluate_readiness(
    partner: PartnerProfile,
    *,
    required_service_code: str | None = None,
    at=None,
) -> Readiness:
    """Decide whether a partner may receive (and accept) offers.

    ``required_service_code`` adds a skill check for a specific job without changing
    the partner's stored skills.
    """
    now = at or timezone.now()
    blockers: list[ReadinessBlocker] = []

    # --- account state -----------------------------------------------------
    if partner.status == PartnerProfile.Status.SUSPENDED:
        blockers.append(
            ReadinessBlocker(
                BlockerCode.SUSPENDED,
                "Your account is suspended",
                partner.suspension_reason,
            )
        )
    elif partner.status != PartnerProfile.Status.APPROVED:
        blockers.append(
            ReadinessBlocker(
                BlockerCode.NOT_APPROVED,
                "Your application is still being reviewed",
                f"status={partner.status}",
            )
        )

    if not partner.phone_verified:
        blockers.append(
            ReadinessBlocker(BlockerCode.PHONE_UNVERIFIED, "Verify your phone number")
        )

    # --- documents ---------------------------------------------------------
    documents = {doc.doc_type: doc for doc in partner.documents.all()}

    identity = documents.get("identity")
    if identity is None or identity.verification_status != identity.VerificationStatus.VERIFIED:
        blockers.append(
            ReadinessBlocker(
                BlockerCode.IDENTITY_NOT_VERIFIED,
                "Your identity document is not verified",
            )
        )

    insurance = documents.get("insurance")
    if insurance is None:
        blockers.append(ReadinessBlocker(BlockerCode.INSURANCE_MISSING, "No insurance certificate on file"))
    elif insurance.is_expired or (
        partner.insurance_expires_at is not None and partner.insurance_expires_at <= now
    ):
        blockers.append(
            ReadinessBlocker(
                BlockerCode.INSURANCE_EXPIRED,
                "Your insurance certificate has expired",
                f"expired={insurance.expires_at or partner.insurance_expires_at}",
            )
        )

    # --- certification -----------------------------------------------------
    if partner.certification_expires_at is None:
        blockers.append(
            ReadinessBlocker(
                BlockerCode.ASSESSMENT_MISSING, "No training certification recorded"
            )
        )
    elif partner.certification_expires_at <= now:
        blockers.append(
            ReadinessBlocker(
                BlockerCode.ASSESSMENT_MISSING,
                "Your training certification has expired",
                f"expired={partner.certification_expires_at.isoformat()}",
            )
        )

    # --- practical assessment --------------------------------------------
    if partner.assessment_passed_at is None:
        blockers.append(
            ReadinessBlocker(
                BlockerCode.ASSESSMENT_MISSING,
                "Complete the practical assessment before taking jobs",
            )
        )

    # --- kit ---------------------------------------------------------------
    kit = list(partner.equipment.all())
    present_codes = {item.item_code for item in kit if item.is_satisfied}
    expired_codes = {
        item.item_code for item in kit if item.status == item.Status.EXPIRED
    }
    required_codes = {code for code, _name, required in DEFAULT_KIT_ITEMS if required}

    missing_required = sorted(required_codes - present_codes)
    if missing_required:
        blockers.append(
            ReadinessBlocker(
                BlockerCode.KIT_INCOMPLETE,
                "Required kit items are missing",
                ",".join(missing_required),
            )
        )
    if expired_codes & required_codes:
        blockers.append(
            ReadinessBlocker(
                BlockerCode.KIT_EXPIRED,
                "Some kit items have expired",
                ",".join(sorted(expired_codes & required_codes)),
            )
        )

    # --- skills ------------------------------------------------------------
    if required_service_code is not None:
        skill = partner.skills.filter(service__code=required_service_code).first()
        if skill is None:
            blockers.append(
                ReadinessBlocker(
                    BlockerCode.SKILL_MISSING,
                    f"You are not trained for {required_service_code}",
                    required_service_code,
                )
            )
        elif not skill.is_current:
            blockers.append(
                ReadinessBlocker(
                    BlockerCode.SKILL_MISSING,
                    f"Your certification for {required_service_code} has expired",
                    required_service_code,
                )
            )

    return Readiness(eligible_for_offers=not blockers, blockers=blockers)


def assert_eligible(
    partner: PartnerProfile, *, required_service_code: str | None = None
) -> Readiness:
    """Raise if a partner may not receive offers."""
    from apps.common.exceptions import PartnerNotEligible

    readiness = evaluate_readiness(
        partner, required_service_code=required_service_code
    )
    if not readiness.eligible_for_offers:
        raise PartnerNotEligible(details={"blockers": [{"code": b.code, "message": b.message, "detail": b.detail} for b in readiness.blockers]})
    return readiness


def expiring_documents(within_days: int = 30, *, at=None) -> list:
    """Documents approaching expiry, so operations can chase renewals."""
    from datetime import timedelta

    now = at or timezone.now()
    horizon = now + timedelta(days=within_days)
    return list(
        PartnerProfile.objects.filter(
            documents__expires_at__isnull=False,
            documents__expires_at__lte=horizon.date(),
        ).distinct()
    )