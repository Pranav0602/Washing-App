"""Masked communication: in-app chat and relayed calls.

Two rules from the PDF are enforced here:

* raw phone numbers are never returned by any endpoint
* a thread is only reachable while the booking is active or inside a short,
  configurable support window after it ends
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import (
    CommsWindowClosed,
    NotFound,
    PermissionDenied,
)
from apps.common.permissions import IsAuthenticatedActor
from apps.comms.models import ChatMessage, ChatThread

logger = logging.getLogger("apps.comms.views")


class ChatMessageSerializer(serializers.ModelSerializer):
    sender_role = serializers.SerializerMethodField()
    is_mine = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = ("id", "sender", "sender_role", "is_mine", "body", "created_at", "read_at")
        read_only_fields = fields

    def get_sender_role(self, obj) -> str:
        roles = set(obj.sender.roles())
        if "partner" in roles:
            return "partner"
        return "customer"

    def get_is_mine(self, obj) -> bool:
        request = self.context.get("request")
        return bool(request and request.user.pk == obj.sender_id)


class ChatMessageInputSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=ChatMessage.MAX_LENGTH)


class ThreadSerializer(serializers.ModelSerializer):
    booking_reference = serializers.CharField(source="booking.reference", read_only=True)
    partner_display_name = serializers.CharField(
        source="partner.display_name", read_only=True, default=None
    )
    masked_counterparty_number = serializers.SerializerMethodField()
    is_open = serializers.BooleanField(read_only=True)
    last_message_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = ChatThread
        fields = (
            "id",
            "booking_reference",
            "partner_display_name",
            "masked_counterparty_number",
            "status",
            "is_open",
            "opened_at",
            "closes_at",
            "closed_at",
            "last_message_at",
        )
        read_only_fields = fields

    def get_masked_counterparty_number(self, obj) -> str | None:
        """A relay number, never the customer's own number."""
        if not obj.is_open:
            return None
        request = self.context.get("request")
        if request is None:
            return None
        is_customer = request.user.pk == obj.customer_id
        counterparty = obj.partner.user if is_customer else obj.customer
        return masking.masked_relay_number(user=counterparty)


def _resolve_thread(reference: str, user) -> ChatThread:
    from apps.bookings.models import Booking

    booking = (
        Booking.objects.select_related("customer", "partner", "partner__user")
        .filter(reference=reference)
        .first()
    )
    if booking is None:
        raise NotFound(f"No booking with reference {reference}.")

    thread = ChatThread.objects.filter(booking=booking).select_related(
        "customer", "partner", "partner__user"
    ).first()
    if thread is None:
        raise NotFound("No conversation exists for this booking.")

    _assert_participant(user, thread)
    return thread


def _assert_participant(user, thread: ChatThread) -> None:
    roles = set(user.roles())
    if roles & {"ops", "admin"}:
        return
    if thread.customer_id == user.pk:
        return
    profile = getattr(user, "partner_profile", None)
    if profile is not None and thread.partner_id == profile.pk:
        return
    raise PermissionDenied("You are not part of this conversation.")


def _assert_open(thread: ChatThread) -> None:
    thread.expire_if_due()
    if not thread.is_open:
        raise CommsWindowClosed(
            "Messaging closes shortly after the job ends.",
            details={
                "status": thread.status,
                "closed_at": thread.closed_at.isoformat() if thread.closed_at else None,
            },
        )


class ThreadCollectionView(APIView):
    permission_classes = [IsAuthenticatedActor]
    throttle_scope = "comms"

    def get(self, request):
        roles = set(request.user.roles())
        queryset = ChatThread.objects.all()
        if roles & {"ops", "admin"}:
            pass
        elif "customer" in roles:
            queryset = queryset.filter(customer=request.user)
        else:
            profile = getattr(request.user, "partner_profile", None)
            queryset = queryset.filter(partner=profile) if profile else queryset.none()

        for thread in queryset:
            thread.expire_if_due()
        return Response(
            ThreadSerializer(queryset, many=True, context={"request": request}).data
        )


class ThreadMessageView(APIView):
    permission_classes = [IsAuthenticatedActor]
    throttle_scope = "comms"

    def get(self, request, reference):
        thread = _resolve_thread(reference, request.user)
        messages = thread.messages.select_related("sender").order_by("created_at")[:200]
        return Response(ChatMessageSerializer(messages, many=True, context={"request": request}).data)

    def post(self, request, reference):
        thread = _resolve_thread(reference, request.user)
        _assert_open(thread)

        serializer = ChatMessageInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            message = ChatMessage.objects.create(
                thread=thread,
                sender=request.user,
                body=serializer.validated_data["body"].strip(),
            )
            ChatThread.objects.filter(pk=thread.pk).update(last_message_at=timezone.now())

        return Response(
            ChatMessageSerializer(message, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class ThreadCallView(APIView):
    """Start a relayed, masked call for the active booking."""

    permission_classes = [IsAuthenticatedActor]
    throttle_scope = "comms"

    def post(self, request, reference):
        thread = _resolve_thread(reference, request.user)
        _assert_open(thread)

        is_customer = request.user.pk == thread.customer_id
        callee = thread.partner.user if is_customer else thread.customer
        counterparty = callee if is_customer else thread.customer

        number = masking.masked_relay_number(user=counterparty, partner=thread.partner)
        session = masking.start_relay_call(
            booking=thread.booking,
            caller=request.user,
            callee=callee,
            thread=thread,
            masked_number=number,
        )
        return Response(
            {
                "call_id": str(session.pk),
                "masked_number": number,
                "expires_at": session.started_at.isoformat(),
                "note": "The number is masked and routed through our relay. It works only while this job is active.",
            },
            status=status.HTTP_201_CREATED,
        )


from apps.comms.services import masking  # noqa: E402