"""Partner self-service endpoints."""

from __future__ import annotations

import logging

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import NotFound, ValidationFailed
from apps.common.permissions import IsPartner
from apps.common.throttling import PartnerLocationThrottle
from apps.partners.models import PartnerProfile
from apps.partners.serializers import (
    AvailabilityInputSerializer,
    EquipmentInputSerializer,
    LocationPingInputSerializer,
    PartnerDocumentSerializer,
    PartnerEquipmentSerializer,
    PartnerProfileSerializer,
    PartnerServiceSkillSerializer,
    PartnerShiftSerializer,
    SkillsInputSerializer,
    UnavailabilityInputSerializer,
    WeeklyAvailabilityInputSerializer,
)
from apps.partners.services import availability as availability_service
from apps.partners.services import location_ingest

logger = logging.getLogger("apps.partners.views")

#: Uploaded verification documents are images or PDFs, within a bounded size.
ALLOWED_DOCUMENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024


def _profile_for(user) -> PartnerProfile:
    profile = getattr(user, "partner_profile", None)
    if profile is None:
        raise NotFound("This account has no partner profile.")
    return profile


class PartnerProfileView(APIView):
    """The signed-in partner's own profile and readiness blockers."""

    permission_classes = [IsPartner]

    def get(self, request):
        profile = _profile_for(request.user)
        data = dict(PartnerProfileSerializer(profile).data)
        data["location"] = location_ingest.location_freshness(profile)
        data["active_shift"] = PartnerShiftSerializer(
            profile.shifts.filter(status="active").order_by("-starts_at").first(), many=False
        ).data
        return Response(data)

    def patch(self, request):
        profile = _profile_for(request.user)
        data = request.data
        # A partner may edit its public details only. Status, commission and payout
        # wiring are operations decisions and are rejected here as well as in the
        # serializer, so a crafted request cannot change them.
        editable = {}
        for field in ("display_name", "bio", "service_radius_km", "default_capacity"):
            if field in data:
                editable[field] = data[field]
        for forbidden in ("status", "commission_bps", "rating_avg", "rating_count",
                          "payout_account_ref", "verified_at", "suspension_reason"):
            if forbidden in data:
                raise ValidationFailed(
                    f"'{forbidden}' cannot be changed by the partner.",
                    details={"field": forbidden},
                )
        for field, value in editable.items():
            setattr(profile, field, value)
        if editable:
            profile.save(update_fields=list(editable) + ["updated_at"])
        return Response(PartnerProfileSerializer(profile).data)


class PartnerAvailabilityView(APIView):
    """Start or end a shift, and manage weekly availability."""

    permission_classes = [IsPartner]

    def put(self, request):
        profile = _profile_for(request.user)
        serializer = AvailabilityInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        action = data.get("action", "start")
        if action == "end":
            availability_service.end_shift(partner=profile)
            return Response({"shift": None, "ended": True})

        zone = None
        if data.get("zone_code"):
            from apps.locations.models import ServiceZone

            zone = get_object_or_404(ServiceZone, code=data["zone_code"], is_active=True)

        if "service_radius_km" in data:
            profile.service_radius_km = data["service_radius_km"]
        if "default_capacity" in data:
            profile.default_capacity = data["default_capacity"]
        profile.save(
            update_fields=[
                field
                for field in ("service_radius_km", "default_capacity", "updated_at")
                if field in data or True
            ]
        )

        starts_at = data.get("starts_at") or timezone.now()
        ends_at = data.get("ends_at") or (starts_at + timezone.timedelta(hours=4))
        result = availability_service.start_shift(
            partner=profile,
            starts_at=starts_at,
            ends_at=ends_at,
            zone=zone,
            declared_capacity_minutes=data.get("declared_capacity_minutes", 0),
        )
        return Response(
            {
                "shift": PartnerShiftSerializer(result.shift).data,
                "ended_previous": result.closed_previous,
                "location_sharing_active": profile.has_active_location_context(),
            },
            status=status.HTTP_201_CREATED,
        )


class PartnerWeeklyAvailabilityView(APIView):
    permission_classes = [IsPartner]

    def put(self, request):
        profile = _profile_for(request.user)
        serializer = WeeklyAvailabilityInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        windows = availability_service.replace_weekly_windows(
            profile, serializer.validated_data["windows"]
        )
        from apps.partners.serializers import PartnerAvailabilityWindowSerializer

        return Response(PartnerAvailabilityWindowSerializer(windows, many=True).data)


class PartnerLocationView(APIView):
    """Ingest a precise location sample.

    Rejected unless the partner is on an active shift or has an active job, and
    rejected when the sample is older than the last accepted one.
    """

    permission_classes = [IsPartner]
    throttle_classes = [PartnerLocationThrottle]
    throttle_scope = "location"

    def post(self, request):
        profile = _profile_for(request.user)
        serializer = LocationPingInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        accepted = location_ingest.record_location(
            partner=profile,
            latitude=data["latitude"],
            longitude=data["longitude"],
            accuracy_m=data.get("accuracy_m"),
            recorded_at=data["recorded_at"],
        )
        return Response(
            {
                "accepted": True,
                "recorded_at": accepted.ping.recorded_at.isoformat(),
                "accuracy_m": accepted.ping.accuracy_m,
                "retention_note": "Location samples are deleted after the configured retention window.",
            },
            status=status.HTTP_202_ACCEPTED,
        )


class PartnerSkillsView(APIView):
    permission_classes = [IsPartner]

    def get(self, request):
        profile = _profile_for(request.user)
        return Response(PartnerServiceSkillSerializer(profile.skills.all(), many=True).data)

    def put(self, request):
        profile = _profile_for(request.user)
        serializer = SkillsInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from apps.catalog.models import ServiceType
        from apps.partners.models import PartnerServiceSkill

        requested = serializer.validated_data["skills"]
        codes = {str(item.get("service_code")) for item in requested}
        services = {service.code: service for service in ServiceType.objects.filter(code__in=codes)}

        unknown = sorted(codes - set(services))
        if unknown:
            raise ValidationFailed(
                "Unknown service codes.", details={"field": "skills", "unknown": unknown}
            )

        with transaction.atomic():
            profile.skills.all().delete()
            created = []
            for item in requested:
                created.append(
                    PartnerServiceSkill.objects.create(
                        partner=profile,
                        service=services[item["service_code"]],
                        proficiency=item.get("proficiency", "trained"),
                    )
                )
        return Response(PartnerServiceSkillSerializer(created, many=True).data)


class PartnerEquipmentView(APIView):
    permission_classes = [IsPartner]

    def get(self, request):
        profile = _profile_for(request.user)
        return Response(PartnerEquipmentSerializer(profile.equipment.all(), many=True).data)

    def put(self, request):
        profile = _profile_for(request.user)
        serializer = EquipmentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)


        known = {item.item_code for item in profile.equipment.all()}
        updated = []
        with transaction.atomic():
            for item in serializer.validated_data["items"]:
                code = str(item.get("item_code"))
                if code not in known:
                    raise ValidationFailed(
                        "Unknown kit item.", details={"field": "item_code", "item_code": code}
                    )
                row = profile.equipment.get(item_code=code)
                row.status = item.get("status", row.status)
                if item.get("notes") is not None:
                    row.notes = str(item["notes"])[:2000]
                row.checked_at = timezone.now()
                row.save(update_fields=["status", "notes", "checked_at", "updated_at"])
                updated.append(row)

        profile.refresh_from_db()
        data = PartnerEquipmentSerializer(updated, many=True).data
        return Response(
            {
                "items": data,
                "readiness": PartnerProfileSerializer(profile).data["readiness"],
            }
        )


class PartnerDocumentCollectionView(APIView):
    """Upload and list the partner's own verification documents."""

    permission_classes = [IsPartner]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        profile = _profile_for(request.user)
        documents = profile.documents.all().order_by("-created_at")
        return Response(
            PartnerDocumentSerializer(
                documents, many=True, context={"can_view_restricted": True}
            ).data
        )

    def post(self, request):
        profile = _profile_for(request.user)
        serializer = PartnerDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationFailed("A file is required.", details={"field": "file"})
        if upload.content_type not in ALLOWED_DOCUMENT_TYPES:
            raise ValidationFailed(
                "Upload a JPEG, PNG, WebP or PDF.",
                details={"field": "file", "allowed": sorted(ALLOWED_DOCUMENT_TYPES)},
            )
        if upload.size > MAX_DOCUMENT_BYTES:
            raise ValidationFailed(
                "That file is too large.", details={"field": "file", "max_bytes": MAX_DOCUMENT_BYTES}
            )

        from apps.evidence.services import storage

        stored = storage.store_upload(
            upload=upload,
            namespace=f"partner-documents/{profile.pk}",
        )
        document = serializer.save(
            partner=profile,
            object_key=stored.object_key,
            checksum_sha256=stored.checksum_sha256,
            content_type=upload.content_type,
            byte_size=upload.size,
        )
        return Response(
            PartnerDocumentSerializer(document, context={"can_view_restricted": True}).data,
            status=status.HTTP_201_CREATED,
        )


class PartnerEarningsView(APIView):
    """Earnings summary. The PDF requires partners to see what they have earned."""

    permission_classes = [IsPartner]

    def get(self, request):
        profile = _profile_for(request.user)
        from django.db.models import Sum

        from apps.payments.models import PartnerPayable
        from apps.payments.serializers import PartnerPayableSerializer

        payables = PartnerPayable.objects.filter(partner=profile).select_related(
            "booking", "payout_batch"
        )
        status_filter = request.query_params.get("status")
        if status_filter:
            payables = payables.filter(status__in=status_filter.split(","))

        totals = payables.aggregate(
            gross=Sum("gross_minor"),
            commission=Sum("commission_minor"),
            adjustment=Sum("adjustment_minor"),
            net=Sum("net_minor"),
        )
        currency = payables.first().currency if payables.exists() else "INR"

        from apps.payments.serializers import PayoutBatchSerializer

        batches = profile.payables.exclude(payout_batch__isnull=True).values_list(
            "payout_batch"
        ).distinct()
        from apps.payments.models import PayoutBatch

        return Response(
            {
                "currency": currency,
                "summary": {
                    "gross_minor": totals["gross"] or 0,
                    "commission_minor": totals["commission"] or 0,
                    "adjustment_minor": totals["adjustment"] or 0,
                    "net_minor": totals["net"] or 0,
                },
                "payables": PartnerPayableSerializer(payables, many=True).data,
                "payout_batches": PayoutBatchSerializer(
                    PayoutBatch.objects.filter(pk__in=[b for b in batches if b]).distinct(),
                    many=True,
                ).data,
            }
        )


class PartnerUnavailabilityView(APIView):
    permission_classes = [IsPartner]

    def post(self, request):
        profile = _profile_for(request.user)
        serializer = UnavailabilityInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        record = availability_service.declare_unavailability(
            partner=profile,
            starts_at=data["starts_at"],
            ends_at=data["ends_at"],
            reason_code=data["reason_code"],
            reason_text=data.get("reason_text", ""),
        )
        # Pending offers must be withdrawn immediately so no new work arrives.
        from apps.dispatch.services import dispatcher

        withdrawn = dispatcher.withdraw_partner_from_pending(partner=profile)
        return Response(
            {
                "id": str(record.pk),
                "starts_at": record.starts_at.isoformat(),
                "ends_at": record.ends_at.isoformat(),
                "reason_code": record.reason_code,
                "pending_offers_withdrawn": withdrawn,
            },
            status=status.HTTP_201_CREATED,
        )