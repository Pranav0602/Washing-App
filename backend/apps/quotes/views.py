"""Quote endpoints."""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import ServiceType, Vehicle
from apps.common.permissions import IsCustomer
from apps.locations.models import Address
from apps.quotes.models import Quote
from apps.quotes.serializers import (
    AcceptQuoteSerializer,
    QuoteRequestSerializer,
    QuoteSerializer,
)
from apps.quotes.services import pricing


class QuoteCollectionView(APIView):
    """POST /quotes - request a transparent, itemised quote."""

    permission_classes = [IsCustomer]
    throttle_scope = "quote"

    def post(self, request):
        serializer = QuoteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        vehicle = get_object_or_404(
            Vehicle, pk=data["vehicle_id"], owner=request.user, is_active=True
        )
        address = get_object_or_404(
            Address, pk=data["address_id"], owner=request.user, is_active=True
        )
        service = get_object_or_404(ServiceType, code=data["service_code"], is_active=True)

        quote = pricing.create_quote(
            customer=request.user,
            vehicle=vehicle,
            address=address,
            service=service,
            addon_codes=data.get("addon_codes") or [],
            booking_mode=data["booking_mode"],
            window_start=data.get("window_start"),
            window_end=data.get("window_end"),
            coupon_code=data.get("coupon_code") or "",
        )
        return Response(QuoteSerializer(quote).data, status=status.HTTP_201_CREATED)


class QuoteDetailView(APIView):
    """Read, accept or decline one of the customer's own quotes."""

    permission_classes = [IsCustomer]

    def get_object(self, request, quote_id):
        return get_object_or_404(Quote, pk=quote_id, customer=request.user)

    def get(self, request, quote_id):
        return Response(QuoteSerializer(self.get_object(request, quote_id)).data)

    def post(self, request, quote_id):
        """``action=accept`` or ``action=decline``."""
        action = str(request.data.get("action", "accept")).lower()
        quote = self.get_object(request, quote_id)

        if action == "accept":
            AcceptQuoteSerializer(data=request.data)
            pricing.accept_quote(quote=quote, customer=request.user)
        elif action == "decline":
            pricing.decline_quote(quote=quote, customer=request.user)
        else:
            from apps.common.exceptions import ValidationFailed

            raise ValidationFailed(
                "action must be 'accept' or 'decline'.", details={"field": "action"}
            )
        quote.refresh_from_db()
        return Response(QuoteSerializer(quote).data)