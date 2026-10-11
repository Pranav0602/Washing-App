"""Payment provider webhook receiver.

Mounted at ``/webhooks/`` rather than under the versioned API: this is a
provider-facing surface with its own authentication (an HMAC signature) and its own
threat model.

Order of operations, as the PDF requires:

1. verify the signature - an invalid one is rejected outright
2. deduplicate on ``(provider, provider_event_id)``
3. persist the event **before** processing it
4. hand processing to the outbox worker, which retries safely
5. surface anything unmatched so it can be reconciled
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.http import Http404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payments.ports import gateway as gateway_port
from apps.webhooks import models as webhook_models

logger = logging.getLogger("apps.webhooks.views")

#: Only these providers have a receiver. Adding one requires an adapter.
SUPPORTED_PROVIDERS = ("sandbox",)


class PaymentWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request, provider):
        if provider not in SUPPORTED_PROVIDERS:
            raise Http404(f"No webhook receiver for provider {provider!r}")

        signature = request.META.get("HTTP_X_SIGNATURE", "")
        adapter = gateway_port.get_gateway()

        event, duplicate = webhook_models.receive(
            provider=provider,
            payload=request.body,
            signature=signature,
            secret=settings.PAYMENT_WEBHOOK_SECRET,
            verifier=adapter.verify_webhook,
        )
        return Response(
            {
                "received": True,
                "duplicate": duplicate,
                "event_id": str(event.pk),
            },
            status=status.HTTP_202_ACCEPTED,
        )