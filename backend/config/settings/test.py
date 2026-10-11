"""Test settings.

Tests run against a real PostgreSQL database (``POSTGRES_TEST_DB``) so that
``ArrayField``, ``JSONField``, ``UUIDField``, constraints and row locking behave
exactly as they do in production. A SQLite fallback would not exercise those.
"""

from __future__ import annotations

from config import env
from config.settings.base import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]

# Speed up hashing and disable password throttling noise in tests.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
AUTH_PASSWORD_VALIDATORS: list[dict] = []

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

CORS_ALLOWED_ORIGINS = ["http://testserver"]
CORS_ALLOW_ALL_ORIGINS = False

SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False

# Deterministic, non-networked integrations.
PAYMENT_GATEWAY = env.get("PAYMENT_GATEWAY", "sandbox")
PAYMENT_WEBHOOK_SECRET = env.get("PAYMENT_WEBHOOK_SECRET", "test-webhook-secret")
PUSH_PROVIDER = "noop"
ETA_PROVIDER = env.get("ETA_PROVIDER", "estimate")
COMMS_PROVIDER = "relay"
EVIDENCE_STORAGE_BACKEND = "filesystem"
EVIDENCE_ROOT = env.get("EVIDENCE_ROOT", "./var/test-evidence")

# Throttles would otherwise make tests flaky; individual throttle tests opt in by
# using the throttle classes directly.
REST_FRAMEWORK = {  # noqa: F405
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_CLASSES": [],
}

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

LOGGING = {  # noqa: F405
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "root": {"handlers": ["null"], "level": "CRITICAL"},
}

MEDIA_ROOT = EVIDENCE_ROOT