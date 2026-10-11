"""Enumerations shared across apps.

These live in ``common`` so that identity registration, locations and catalog can
all validate against the same vocabulary without importing one another.
"""

from __future__ import annotations

from django.db import models


class SiteType(models.TextChoices):
    """Where the vehicle is washed.

    The PDF requires a method matrix per site type: a service that cannot be
    performed safely at a site must be blocked in the app, not merely discouraged.
    """

    STANDALONE_HOUSE = "standalone_house", "Independent house"
    APARTMENT = "apartment", "Apartment"
    BASEMENT = "basement", "Basement / parking"
    SOCIETY = "society", "Society / gated community"
    COMMERCIAL = "commercial", "Commercial site"


class VehicleType(models.TextChoices):
    CAR = "car", "Car"
    SUV = "suv", "SUV"
    TRUCK = "truck", "Truck"
    VAN = "van", "Van"
    BIKE = "bike", "Motorcycle"
    SCOOTER = "scooter", "Scooter"


class VehicleSizeTier(models.TextChoices):
    """Drives the vehicle-tier component of the price rule.

    Tier is derived from the vehicle type rather than trusted from the client.
    """

    S = "S", "Small"
    M = "M", "Medium"
    L = "L", "Large"
    H = "H", "Extra large"


#: Maps a vehicle type to its price tier. Overridden per catalog if needed.
VEHICLE_TYPE_TO_TIER: dict[str, str] = {
    VehicleType.BIKE: VehicleSizeTier.S,
    VehicleType.SCOOTER: VehicleSizeTier.S,
    VehicleType.CAR: VehicleSizeTier.M,
    VehicleType.SUV: VehicleSizeTier.L,
    VehicleType.VAN: VehicleSizeTier.L,
    VehicleType.TRUCK: VehicleSizeTier.H,
}


class BookingMode(models.TextChoices):
    """Scheduled slots are the reliable baseline; on-demand is capped."""

    SCHEDULED = "scheduled", "Scheduled"
    ON_DEMAND = "on_demand", "On demand"


class ActorType(models.TextChoices):
    """Who caused a booking transition. Recorded on every event."""

    CUSTOMER = "customer", "Customer"
    PARTNER = "partner", "Partner"
    OPS = "ops", "Operations"
    ADMIN = "admin", "Administrator"
    SYSTEM = "system", "System"
    PROVIDER = "provider", "Payment provider"


class EvidenceType(models.TextChoices):
    PRE_CONDITION = "pre_condition", "Pre-service condition"
    POST_SERVICE = "post_service", "After service"
    DAMAGE = "damage", "Damage"
    OTHER = "other", "Other"


class EvidenceAccessPolicy(models.TextChoices):
    """Who may read an evidence object.

    Identity documents and sensitive evidence must not be readable by general
    support, so access is an explicit policy rather than a blanket permission.
    """

    CUSTOMER_PARTNER_OPS = "customer_partner_ops", "Customer, partner and operations"
    OPS_ONLY = "ops_only", "Operations only"
    ADMIN_ONLY = "admin_only", "Administrator only"


class EvidenceUploadStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    UPLOADED = "uploaded", "Uploaded"
    FAILED = "failed", "Failed"
    QUARANTINED = "quarantined", "Quarantined"
    DELETED = "deleted", "Deleted"


SUPPORTED_SITE_TYPES = tuple(SiteType.values)
SUPPORTED_VEHICLE_TYPES = tuple(VehicleType.values)