"""Rate limiting.

The PDF requires rate limits on sensitive endpoints. A view opts in by setting
``throttle_scope`` to a scope name declared in ``DEFAULT_THROTTLE_RATES``, and this
throttle enforces **two windows** for that scope:

* a short *burst* window, which protects against a flood or a runaway retry loop
* a longer *sustained* window, which caps total volume

Both rates derive from the single configured value, so a deployment tunes one
number per endpoint rather than two that can drift apart.

Off-shift partner location pings are exempt from consuming budget because nothing is
stored while a partner is not in an active location-sharing context.
"""

from __future__ import annotations

from rest_framework.throttling import SimpleRateThrottle


def _configured_rate(scope: str) -> str | None:
    from django.conf import settings

    rates = getattr(settings, "REST_FRAMEWORK", {}).get("DEFAULT_THROTTLE_RATES", {})
    return rates.get(scope)


def _window_seconds(rate: str) -> int | None:
    try:
        return int(rate.split("/", 1)[1])
    except (IndexError, ValueError):
        return None


def burst_rate(rate: str) -> str:
    """Compress a long window into a short one at the same budget."""
    number, _, per = rate.partition("/")
    seconds = _window_seconds(rate)
    if seconds is None:
        return f"{number}/min"
    if seconds >= 3600:
        return f"{max(int(number) // 60, 1)}/min"
    if seconds >= 60:
        return f"{number}/min"
    return rate


def sustained_rate(rate: str) -> str:
    """Stretch a short window into an hour at the same budget."""
    number, _, per = rate.partition("/")
    seconds = _window_seconds(rate)
    if seconds is None:
        return f"{int(number) * 60}/hour"
    if seconds >= 3600:
        return rate
    return f"{int(number) * 60}/hour"


class DualWindowThrottle(SimpleRateThrottle):
    """Enforces the burst and sustained windows for a view's ``throttle_scope``."""

    def __init__(self) -> None:
        # SimpleRateThrottle.__init__ resolves a single rate from a static scope.
        # This throttle derives its rates per request from the view, so the base
        # initialisation (which would raise ImproperlyConfigured) is skipped.
        self.rate = None
        self.num_requests = None
        self.duration = None
        self.key = None
        self.history = []
        self.now = None

    def allow_request(self, request, view):
        base_scope = getattr(view, "throttle_scope", None)
        if not base_scope:
            return True

        rate = _configured_rate(base_scope)
        if not rate:
            return True

        if self._skip(request):
            return True

        for suffix, derived in (("burst", burst_rate(rate)), ("sustained", sustained_rate(rate))):
            allowed, wait = self._check_window(request, f"{base_scope}_{suffix}", derived)
            if not allowed:
                self.wait_time = wait
                return False
        return True

    def _skip(self, request) -> bool:
        return False

    def _check_window(self, request, scope: str, rate: str) -> tuple[bool, float]:
        """Evaluate one window, returning ``(allowed, retry_after_seconds)``."""
        self.scope = scope
        self.rate = rate
        self.num_requests, self.duration = self.parse_rate(rate)
        self.key = self.get_cache_key(request)
        self.history = self.cache.get(self.key, [])
        self.now = self.timer()

        # Drop entries that have fallen out of the window.
        while self.history and self.history[-1] <= self.now - self.duration:
            self.history.pop()

        if len(self.history) >= self.num_requests:
            return False, self.duration

        self.history.append(self.now)
        self.cache.set(self.key, self.history, self.duration)
        return True, 0.0

    def get_cache_key(self, request) -> str:
        """Bucket per authenticated user where possible, else per client IP.

        Keyed by the derived window scope so the burst and sustained counters stay
        independent.
        """
        user = getattr(request, "user", None)
        if getattr(user, "is_authenticated", False):
            ident = f"user:{user.pk}"
        else:
            ident = f"ip:{self.get_ident(request)}"
        return f"throttle:{self.scope}:{ident}"


class BurstThrottle(DualWindowThrottle):
    """Primary throttle class. Applied project-wide via ``DEFAULT_THROTTLE_CLASSES``."""


class PartnerLocationThrottle(DualWindowThrottle):
    """Location limiter that ignores pings sent outside an active context.

    Authorisation already rejects off-shift writes, so this exists to stop a single
    on-shift partner from flooding the location table.
    """

    def _skip(self, request) -> bool:
        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False):
            return False
        profile = getattr(user, "partner_profile", None)
        if profile is None:
            return False
        return not profile.has_active_location_context()