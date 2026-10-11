"""Notification endpoints: the in-app feed, which always works.

Push is an enhancement layered on top of this feed. The PDF requires push and
in-app status updates, and a polling fallback when push is unavailable.
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import PermissionDenied
from apps.common.permissions import IsAuthenticatedActor
from apps.notifications.models import Notification, PushDevice


class NotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.BooleanField(read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = Notification
        fields = (
            "id",
            "kind",
            "kind_label",
            "title",
            "body",
            "data",
            "booking_id",
            "read_at",
            "is_read",
            "created_at",
        )
        read_only_fields = fields


class PushDeviceSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=255)
    platform = serializers.ChoiceField(choices=["ios", "android", "web"])


class NotificationCollectionView(APIView):
    permission_classes = [IsAuthenticatedActor]

    def get(self, request):
        queryset = Notification.objects.filter(user=request.user)
        if request.query_params.get("unread_only") == "true":
            queryset = queryset.filter(read_at__isnull=True)
        if request.query_params.get("kind"):
            queryset = queryset.filter(kind__in=request.query_params["kind"].split(","))
        limit = min(int(request.query_params.get("limit", 50)), 200)
        return Response(
            {
                "count": queryset.count(),
                "unread_count": Notification.objects.filter(
                    user=request.user, read_at__isnull=True
                ).count(),
                "results": NotificationSerializer(queryset[:limit], many=True).data,
            }
        )


class NotificationReadView(APIView):
    permission_classes = [IsAuthenticatedActor]

    def patch(self, request, notification_id):
        notification = get_object_or_404(Notification, pk=notification_id)
        if notification.user_id != request.user.pk:
            raise PermissionDenied("You may only read your own notifications.")
        notification.mark_read()
        return Response(NotificationSerializer(notification).data)


class NotificationReadAllView(APIView):
    permission_classes = [IsAuthenticatedActor]

    def post(self, request):
        updated = Notification.objects.filter(
            user=request.user, read_at__isnull=True
        ).update(read_at=timezone.now())
        return Response({"updated": updated}, status=status.HTTP_200_OK)


class PushDeviceCollectionView(APIView):
    """Register and remove the device's push token."""

    permission_classes = [IsAuthenticatedActor]

    def post(self, request):
        serializer = PushDeviceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device, _created = PushDevice.objects.update_or_create(
            token=serializer.validated_data["token"],
            defaults={
                "user": request.user,
                "platform": serializer.validated_data["platform"],
                "is_active": True,
                "failure_count": 0,
                "disabled_at": None,
            },
        )
        return Response(
            {"id": str(device.pk), "token": device.token, "platform": device.platform},
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request):
        token = request.query_params.get("token")
        if not token:
            from apps.common.exceptions import ValidationFailed

            raise ValidationFailed("token is required.", details={"field": "token"})
        PushDevice.objects.filter(user=request.user, token=token).update(is_active=False)
        return Response(status=status.HTTP_204_NO_CONTENT)