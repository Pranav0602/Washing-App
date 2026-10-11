"""Request/response middleware."""

from __future__ import annotations

import logging
import time
import uuid

logger = logging.getLogger("apps.common.request")


class RequestIdMiddleware:
    """Attach a correlation id to every request and echo it back.

    The PDF requires request IDs on responses and in logs so a mobile report can
    be traced to the exact server-side request.
    """

    HEADER = "HTTP_X_REQUEST_ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.META.get(self.HEADER)
        # Only trust a client-supplied id if it is a sane length and charset.
        request_id = (
            incoming.strip()
            if incoming and len(incoming) <= 64 and incoming.isprintable()
            else uuid.uuid4().hex
        )
        request.request_id = request_id
        response = self.get_response(request)
        response["X-Request-Id"] = request_id
        return response


class RequestAuditMiddleware:
    """Record method, path, status and duration for each API request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.monotonic()
        response = self.get_response(request)
        duration_ms = int((time.monotonic() - started) * 1000)

        if request.path.startswith("/api/"):
            user = getattr(request, "user", None)
            actor_id = getattr(user, "pk", None) if getattr(user, "is_authenticated", False) else None
            logger.info(
                "api_request",
                extra={
                    "request_id": getattr(request, "request_id", None),
                    "method": request.method,
                    "path": request.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                    "user_id": str(actor_id) if actor_id else None,
                    "ip": _client_ip(request),
                },
            )
        response["X-Response-Time-Ms"] = str(duration_ms)
        return response


def _client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")