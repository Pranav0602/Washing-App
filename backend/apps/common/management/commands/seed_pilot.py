"""Seed a usable pilot dataset.

Creates service zones with real polygons and windows, a catalog with services and
add-ons, a locked price rule version, and accounts for each role.

Idempotent: safe to re-run. Existing rows are updated rather than duplicated.

    python manage.py seed_pilot --demo-users
"""

from __future__ import annotations

import math
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import AddOn, PriceRuleVersion, ServiceType
from apps.common.enums import SiteType
from apps.identity.models import ROLE_ADMIN, ROLE_CUSTOMER, ROLE_OPS, ROLE_PARTNER, User
from apps.locations.models import ServiceZone, SiteRestriction, ZoneServiceWindow
from apps.partners.models import PartnerProfile
from apps.partners.services.readiness import DEFAULT_KIT_ITEMS

# Zone centre: Pune, India. Rough square covering the whole city.
ZONE_CENTRE_LAT = 18.5204
ZONE_CENTRE_LNG = 73.8567


def square_polygon(lat: float, lng: float, half_km: float = 3.0) -> dict:
    """A GeoJSON square around a centre point, sized in kilometres."""
    lat_delta = half_km / 111.32
    lng_delta = half_km / (111.32 * math.cos(math.radians(lat)))

    min_lat, max_lat = lat - lat_delta, lat + lat_delta
    min_lng, max_lng = lng - lng_delta, lng + lng_delta

    # GeoJSON order is [lng, lat], and the ring must be closed.
    ring = [
        [min_lng, min_lat],
        [max_lng, min_lat],
        [max_lng, max_lat],
        [min_lng, max_lat],
        [min_lng, min_lat],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


class Command(BaseCommand):
    help = "Seed zones, catalog, pricing and accounts for local development."

    def add_arguments(self, parser):
        parser.add_argument(
            "--demo-users",
            action="store_true",
            help="Also create demo customer, partner and operations accounts.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        zone = self._zone()
        self._windows(zone)
        self._restrictions()
        rule = self._price_rule()
        services = self._services()
        self._addons()
        self._staff(options["demo_users"])

        self.stdout.write(self.style.SUCCESS("Pilot dataset ready."))
        self.stdout.write(f"  zone           : {zone.code} ({zone.name})")
        self.stdout.write(f"  services       : {len(services)}")
        self.stdout.write(f"  price rule     : {rule.version} ({rule.currency})")
        if options["demo_users"]:
            self.stdout.write(
                self.style.WARNING(
                    "  demo accounts  : created with fixed codes for local use only."
                )
            )

    # ------------------------------------------------------------------- zones

    def _zone(self) -> ServiceZone:
        polygon = square_polygon(ZONE_CENTRE_LAT, ZONE_CENTRE_LNG, half_km=30.0)
        lats = [point[1] for point in polygon["coordinates"][0]]
        lngs = [point[0] for point in polygon["coordinates"][0]]

        zone, created = ServiceZone.objects.update_or_create(
            code="ZONE-CENTRAL",
            defaults={
                "name": "Pune — all areas",
                "city": "Pune",
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
                "on_demand_radius_km": 30.0,
            },
        )
        self.stdout.write(f"{'created' if created else 'updated'} zone {zone.code}")
        return zone

    def _windows(self, zone: ServiceZone) -> None:
        """08:00-20:00 daily, with on-demand allowed in the middle of the day."""
        for weekday in range(7):
            ZoneServiceWindow.objects.update_or_create(
                zone=zone,
                weekday=weekday,
                defaults={
                    "opens_at_minutes": 8 * 60,
                    "closes_at_minutes": 20 * 60,
                    "allows_scheduled": True,
                    "allows_on_demand": True,
                    "max_jobs": 20,
                },
            )

    def _restrictions(self) -> None:
        """The method matrix.

        Basement and commercial sites block the water-intensive interior service,
        because the PDF requires unsupported methods to be blocked rather than
        discouraged, and requires site rules to be confirmed before launch.
        """
        for site_type in SiteType.values:
            SiteRestriction.objects.update_or_create(
                zone=None,
                site_type=site_type,
                defaults={
                    "allowed_service_codes": [],
                    "prohibited_service_codes": (
                        ["INT_FULL"] if site_type in (SiteType.BASEMENT, SiteType.COMMERCIAL) else []
                    ),
                    "requires_property_approval": site_type
                    in (SiteType.SOCIETY, SiteType.APARTMENT),
                    "requires_external_water": site_type
                    in (SiteType.APARTMENT, SiteType.SOCIETY, SiteType.BASEMENT),
                    "requires_external_power": site_type in (SiteType.BASEMENT,),
                    "notes": (
                        "Interior service needs a permitted waste-water route; blocked until "
                        "site rules are confirmed."
                        if site_type in (SiteType.BASEMENT, SiteType.COMMERCIAL)
                        else ""
                    ),
                },
            )

    # ----------------------------------------------------------------- catalog

    def _price_rule(self) -> PriceRuleVersion:

        rule, created = PriceRuleVersion.objects.update_or_create(
            version="2026-10-01",
            defaults={
                "kind": PriceRuleVersion.Kind.STANDARD,
                "display_name": "Launch pricing",
                "currency": "INR",
                # Tax stays zero until a jurisdiction is confirmed.
                "tax_bps": 0,
                "platform_fee_minor": 4900,
                "vehicle_tier_minor": {"S": 0, "M": 60000, "L": 140000, "H": 260000},
                "zone_travel_minor": {"default": 30000, "per_km_minor": 4000},
                "discount_rules": {
                    "WELCOME10": {"type": "percent", "bps": 1000},
                    "FLAT150": {"type": "fixed", "amount_minor": 15000},
                },
                "effective_from": timezone.now() - timedelta(days=1),
                "effective_to": None,
                "is_locked": True,
                "created_by": None,
                "notes": "Seed ruleset. Tax deliberately zero pending jurisdiction confirmation.",
            },
        )
        self.stdout.write(f"{'created' if created else 'updated'} price rule {rule.version}")
        return rule

    def _services(self) -> list[ServiceType]:
        rows = [
            {
                "code": "EXT_QUICK",
                "name": "Quick exterior",
                "description": "Foam pre-wash, hand wash, rinse and dry.",
                "base_price_minor": 39900,
                "expected_duration_minutes": 35,
                "allowed_site_types": list(SiteType.values),
                "inclusions": ["Foam pre-wash", "Hand wash", "Rinse", "Spot-free dry"],
                "exclusions": ["Interior cleaning", "Wheels and tyres deep clean"],
                "sort_order": 10,
            },
            {
                "code": "EXT_INT",
                "name": "Exterior and interior",
                "description": "Quick exterior plus interior vacuum, dashboard and glass.",
                "base_price_minor": 79900,
                "expected_duration_minutes": 75,
                # No basement or commercial: waste-water routing must be confirmed.
                "allowed_site_types": [
                    SiteType.STANDALONE_HOUSE,
                    SiteType.APARTMENT,
                    SiteType.SOCIETY,
                ],
                "inclusions": [
                    "Quick exterior wash",
                    "Interior vacuum",
                    "Dashboard and trim clean",
                    "Interior glass",
                ],
                "exclusions": ["Steam cleaning", "Leather deep clean", "Odour treatment"],
                "sort_order": 20,
            },
            {
                "code": "INT_FULL",
                "name": "Full interior detail",
                "description": "Deep interior clean with shampooing.",
                "base_price_minor": 149900,
                "expected_duration_minutes": 150,
                "allowed_site_types": [SiteType.STANDALONE_HOUSE, SiteType.SOCIETY],
                "inclusions": ["Shampooing", "Deep vacuum", "Trim and vent clean"],
                "exclusions": ["Engine bay", "Undercarriage"],
                "sort_order": 30,
            },
        ]
        result = []
        for row in rows:
            currency = self._currency()
            service, _ = ServiceType.objects.update_or_create(
                code=row["code"],
                defaults={**row, "currency": currency, "is_active": True},
            )
            result.append(service)
        self.stdout.write(f"{len(result)} service(s) available")
        return result

    def _currency(self) -> str:
        from django.conf import settings

        return settings.DEFAULT_CURRENCY

    def _addons(self) -> None:
        currency = self._currency()
        rows = [
            {
                "code": "ADD_WAX",
                "name": "Wax finish",
                "description": "Hand-applied wax for extra gloss and protection.",
                "price_minor": 49900,
                "duration_delta_minutes": 20,
                "allowed_service_codes": ["EXT_QUICK", "EXT_INT", "INT_FULL"],
                "sort_order": 10,
            },
            {
                "code": "ADD_SHAMPOO",
                "name": "Seat shampooing",
                "description": "Shampoo fabric seats to lift embedded dirt.",
                "price_minor": 59900,
                "duration_delta_minutes": 30,
                "allowed_service_codes": ["EXT_INT", "INT_FULL"],
                "sort_order": 20,
            },
            {
                "code": "ADD_HEADLIGHT",
                "name": "Headlight restoration",
                "description": "Polish and seal headlight lenses.",
                "price_minor": 24900,
                "duration_delta_minutes": 15,
                "allowed_site_types": list(SiteType.values),
                "sort_order": 30,
            },
        ]
        for row in rows:
            AddOn.objects.update_or_create(
                code=row["code"],
                defaults={**row, "currency": currency, "is_active": True},
            )
        self.stdout.write(f"{len(rows)} add-on(s) available")

    # ---------------------------------------------------------------- accounts

    def _staff(self, demo: bool) -> None:
        """Always ensure an administrator exists so the console is reachable."""
        if not User.objects.filter(role_grants__role=ROLE_ADMIN).exists():
            admin, created = User.objects.get_or_create(
                phone="+919000000001",
                defaults={
                    "full_name": "Operations Administrator",
                    "is_staff_account": True,
                    "account_complete": True,
                },
            )
            if created:
                admin.set_password("ChangeMe-Admin-2026")
                admin.save()
                admin.grant_role(ROLE_ADMIN)
                self.stdout.write(
                    self.style.WARNING(
                        "  created admin +919000000001 with a temporary password; change it."
                    )
                )

        if not demo:
            return

        customer, created = User.objects.get_or_create(
            phone="+919000000010",
            defaults={"full_name": "Demo Customer", "account_complete": True},
        )
        if created:
            customer.grant_role(ROLE_CUSTOMER)

        partner_user, created = User.objects.get_or_create(
            phone="+919000000020",
            defaults={"full_name": "Demo Partner", "account_complete": True},
        )
        if created:
            partner_user.grant_role(ROLE_PARTNER)

        profile, _ = PartnerProfile.objects.get_or_create(
            user=partner_user,
            defaults={
                "display_name": "Demo Partner",
                "status": PartnerProfile.Status.PENDING_VERIFICATION,
                "phone_verified": True,
                "commission_bps": 1500,
                "service_radius_km": 10.0,
                "default_capacity": 4,
                "home_zone": ServiceZone.objects.filter(code="ZONE-CENTRAL").first(),
            },
        )

        for code, name, required in DEFAULT_KIT_ITEMS:
            profile.equipment.get_or_create(
                item_code=code,
                defaults={"name": name, "required": required},
            )

        if not User.objects.filter(role_grants__role=ROLE_OPS).exists():
            ops_user = User.objects.create_user(
                phone="+919000000002",
                password="ChangeMe-Ops-2026",
                full_name="Operations Agent",
                account_complete=True,
                is_staff_account=True,
            )
            ops_user.grant_role(ROLE_OPS)