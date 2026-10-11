"""Idempotency for create, capture and refund commands.

Implemented as a view mixin rather than middleware so that only the endpoints that
genuinely need replay protection opt in.

Behaviour:

* missing ``Idempotency-Key`` on a protected action -> ``400 idempotency_key_required``
* first call -> the key is claimed, then the work runs
* repeat call with the same key and same payload -> the stored response is replayed
* repeat call with the same key and a different payload -> ``409 idempotency_key_reuse_mismatch``
* a failed attempt releases the key so the client can retry honestly

The fingerprint is computed from the **raw request body** rather than
``request.data``. ``request.data`` does not exist until DRF has initialised the
request, and reading the parsed body here would consume the upload stream. Django
caches ``request.body``, so reading it in this mixin is safe and the handler still
sees an intact stream.

File uploads are deliberately **not** wrapped by this mixin: evidence upload is made
idempotent by a client-supplied ``client_photo_id`` inside the evidence service,
which is the right place for a large multipart body.

The mixin intercepts :meth:`dispatch`, so it works for plain ``APIView`` endpoints as
well as ``ViewSet`` actions.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.response import Response

from apps.common.exceptions import (
    DomainError,
    IdempotencyKeyRequired,
    IdempotencyKeyReuseMismatch,
    error_payload,
)
from apps.common.infrastructure import IdempotencyRecord

HEADER = "HTTP_IDEMPOTENCY_KEY"
MAX_KEY_LENGTH = 128
METHODS = frozenset({"post", "put", "patch", "delete"})


def _fingerprint(scope: str, body: bytes) -> str:
    material = scope.encode() + b"\x00" + (body or b"")
    return hashlib.sha256(material).hexdigest()


def _jsonable(value):
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class IdempotentCommandMixin:
    """Require idempotency on the wrapped actions.

    Usage on an ``APIView``::

        class BookingCollectionView(IdempotentCommandMixin, APIView):
            idempotent_actions = {"post"}
    """

    #: Action names (viewset) or HTTP method names (APIView), lower-cased.
    idempotent_actions: set[str] = set()
    idempotency_scope: str = ""

    def idempotency_ttl(self) -> timedelta:
        from django.conf import settings

        return timedelta(hours=settings.IDEMPOTENCY_TTL_HOURS)

    # ------------------------------------------------------------------ plumbing

    def _resolve_action(self, request, kwargs) -> str | None:
        action = kwargs.get("action")
        if action:
            return str(action).lower()
        method = request.method.lower()
        return method if method in METHODS else None

    def dispatch(self, request, *args, **kwargs):
        action = self._resolve_action(request, kwargs)
        if action not in self.idempotent_actions:
            return super().dispatch(request, *args, **kwargs)

        # This mixin answers a few requests before DRF's dispatch runs, so it must
        # reproduce the small amount of view state that finalisation relies on.
        self.request = request
        self.headers = self.default_response_headers

        try:
            key = self._require_key(request)
            scope = self.idempotency_scope or f"{self.__class__.__name__}:{action}"

            # Read the raw body now: Django caches it, so the handler still sees it.
            body = request.body if request.method in ("POST", "PUT", "PATCH") else b""
            fingerprint = _fingerprint(scope, body)

            record, created = self._claim(key, scope, fingerprint, request)
        except DomainError as exc:
            return self._error_response(request, exc, *args, **kwargs)

        if not created:
            if record.request_fingerprint != fingerprint:
                return self._error_response(
                    request,
                    IdempotencyKeyReuseMismatch(
                        "This idempotency key was used with a different request body.",
                        details={"idempotency_key": key},
                    ),
                    *args,
                    **kwargs,
                )
            if record.status == IdempotencyRecord.Status.COMPLETED:
                replay = Response(record.response_body, status=record.response_code)
                return self.finalize_response(request, replay, *args, **kwargs)
            return self._error_response(
                request,
                IdempotencyKeyReuseMismatch(
                    "A request with this idempotency key is still being processed.",
                    details={"idempotency_key": key},
                ),
                *args,
                **kwargs,
            )

        try:
            with transaction.atomic():
                response = super().dispatch(request, *args, **kwargs)
                if response.status_code < 400:
                    self._persist(record, response)
                else:
                    # A failed attempt must not burn the key; the client will retry.
                    self._release(record)
                    return response
        except Exception:
            self._release(record)
            raise

        return response

    def _error_response(self, request, exc: DomainError, *args, **kwargs) -> Response:
        """Render a pre-dispatch failure in the standard error envelope.

        Raising here would bypass DRF's exception handling and surface as a 500, so
        the envelope is built directly.
        """
        response = Response(
            error_payload(exc.code, exc.message, exc.details, getattr(request, "request_id", None)),
            status=exc.status_code,
        )
        return self.finalize_response(request, response, *args, **kwargs)

    def _require_key(self, request) -> str:
        key = (request.META.get(HEADER) or "").strip()
        if not key:
            raise IdempotencyKeyRequired
        if len(key) > MAX_KEY_LENGTH:
            raise IdempotencyKeyRequired(
                f"Idempotency-Key must be at most {MAX_KEY_LENGTH} characters."
            )
        return key

    def _claim(self, key, scope, fingerprint, request) -> tuple[IdempotencyRecord, bool]:
        user = (
            request.user.pk
            if getattr(request, "user", None) and request.user.is_authenticated
            else None
        )
        record = IdempotencyRecord(
            key=key,
            user_id=user,
            scope=scope,
            request_fingerprint=fingerprint,
            status=IdempotencyRecord.Status.IN_PROGRESS,
            expires_at=timezone.now() + self.idempotency_ttl(),
        )
        try:
            with transaction.atomic():
                record.save(force_insert=True)
            return record, True
        except IntegrityError:
            existing = IdempotencyRecord.objects.filter(key=key).first()
            if existing is None:
                # The conflicting row vanished between the conflict and this read.
                raise IdempotencyKeyReuseMismatch(
                    "A request with this idempotency key is still being processed.",
                    details={"idempotency_key": key},
                ) from None
            return existing, False

    def _persist(self, record: IdempotencyRecord, response) -> None:
        body = response.data
        if hasattr(body, "data"):  # paginated envelope
            body = body.data
        IdempotencyRecord.objects.filter(pk=record.pk).update(
            status=IdempotencyRecord.Status.COMPLETED,
            response_code=response.status_code,
            response_body=_jsonable(body),
        )

    def _release(self, record: IdempotencyRecord) -> None:
        IdempotencyRecord.objects.filter(pk=record.pk).delete()