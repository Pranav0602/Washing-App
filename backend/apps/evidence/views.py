"""Evidence upload and download endpoints."""

from __future__ import annotations

import logging

from django.http import FileResponse
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import Gone, NotFound, ValidationFailed
from apps.common.permissions import IsAuthenticatedActor
from apps.common.throttling import PartnerLocationThrottle
from apps.evidence.serializers import EvidenceSerializer, EvidenceUploadSerializer
from apps.evidence.services import evidence_service, storage

logger = logging.getLogger("apps.evidence.views")


class EvidenceUploadView(APIView):
    """Attach a photo to a booking. Idempotent on ``client_photo_id``."""

    permission_classes = [IsAuthenticatedActor]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    throttle_classes = [PartnerLocationThrottle]
    throttle_scope = "evidence"

    def post(self, request, reference):
        from apps.bookings.models import Booking

        booking = Booking.objects.filter(reference=reference).select_related("customer", "partner").first()
        if booking is None:
            raise NotFound(f"No booking with reference {reference}.")

        serializer = EvidenceUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationFailed("A photo file is required.", details={"field": "file"})

        checks = serializer.validated_data.get("checks") or {}
        if isinstance(checks, str):
            import json

            try:
                checks = json.loads(checks)
            except ValueError:
                raise ValidationFailed(
                    "checks must be a JSON object.", details={"field": "checks"}
                ) from None

        evidence = evidence_service.attach_photo(
            booking=booking,
            uploader=request.user,
            upload=upload,
            evidence_type=serializer.validated_data["evidence_type"],
            captured_at=serializer.validated_data["captured_at"],
            client_photo_id=serializer.validated_data.get("client_photo_id", ""),
            sequence=serializer.validated_data.get("sequence", 0),
            checks=checks,
            access_policy=serializer.validated_data.get(
                "access_policy", "customer_partner_ops"
            ),
        )
        return Response(EvidenceSerializer(evidence).data, status=201)


class EvidenceListView(APIView):
    """Evidence on a booking that the caller is permitted to see."""

    permission_classes = [IsAuthenticatedActor]

    def get(self, request, reference):
        from apps.bookings.models import Booking

        booking = (
            Booking.objects.select_related("customer", "partner")
            .filter(reference=reference)
            .first()
        )
        if booking is None:
            raise NotFound(f"No booking with reference {reference}.")

        rows = [
            evidence_service.get_readable_evidence(evidence_id=row.pk, actor=request.user)
            for row in booking.evidence.all()
        ]
        return Response(EvidenceSerializer(rows, many=True).data)


class EvidenceFileView(APIView):
    """Download one evidence object.

    Requires a valid short-lived signature as well as authorisation, so a leaked URL
    cannot be replayed later or by an unrelated account.
    """

    permission_classes = [IsAuthenticatedActor]

    def get(self, request, evidence_id):
        token = request.query_params.get("token", "")
        evidence = evidence_service.get_readable_evidence(evidence_id=evidence_id, actor=request.user)

        if not storage.verify_signature(object_key=evidence.object_key, token=token):
            raise ValidationFailed(
                "The download link is invalid or has expired. Request a new one.",
                code="invalid_signature",
                details={"evidence_id": str(evidence.pk)},
            )

        try:
            path, content_type = storage.read_object(object_key=evidence.object_key)
        except FileNotFoundError:
            raise Gone("That file is no longer available.") from None
        except PermissionError:
            raise ValidationFailed("Invalid evidence reference.") from None

        response = FileResponse(path.open("rb"), content_type=content_type)
        response["Content-Length"] = str(path.stat().st_size)
        response["Cache-Control"] = "private, no-store"
        return response