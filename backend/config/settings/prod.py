"""Production settings.

Refuses to boot unless every secret is explicitly provided, so a misconfigured
deployment fails at startup rather than serving traffic with a development key.
"""

from __future__ import annotations

from config import env
from config.settings import base
from config.settings.base import *  # noqa: F403

DEBUG = False

# --------------------------------------------------------------------------- guard

_REQUIRED_IN_PROD = (
    "DJANGO_SECRET_KEY",
    "POSTGRES_PASSWORD",
    "JWT_SIGNING_KEY",
    "OTP_PEPPER",
    "PAYMENT_WEBHOOK_SECRET",
)
_missing = sorted(name for name in _REQUIRED_IN_PROD if not env.get(name))
if _missing:
    raise env.MissingSettingError(
        "Refusing to start in production without: " + ", ".join(_missing)
    )

if env.get("DJANGO_SECRET_KEY") == base.SECRET_KEY:
    raise env.MissingSettingError(
        "DJANGO_SECRET_KEY is unset so JWT_SIGNING_KEY fell back to it. "
        "Generate a dedicated JWT signing key for this deployment."
    )

if env.get("JWT_SIGNING_KEY") == base.SECRET_KEY:
    raise env.MissingSettingError(
        "JWT_SIGNING_KEY must differ from DJANGO_SECRET_KEY so that a leaked Django "
        "key cannot be used to forge access tokens."
    )

# ----------------------------------------------------------------------- hardening

ALLOWED_HOSTS = env.get_list("DJANGO_ALLOWED_HOSTS", [])
if not ALLOWED_HOSTS:
    raise env.MissingSettingError("DJANGO_ALLOWED_HOSTS must list the deployed hostnames.")

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = env.get_bool("SECURE_SSL_REDIRECT", True)
SECURE_HSTS_SECONDS = env.get_int("SECURE_HSTS_SECONDS", 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.get_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
SECURE_HSTS_PRELOAD = env.get_bool("SECURE_HSTS_PRELOAD", True)

CORS_ALLOWED_ORIGINS = env.get_list("CORS_ALLOWED_ORIGINS", [])
CORS_ALLOW_ALL_ORIGINS = False

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DATABASES["default"]["CONN_MAX_AGE"] = env.get_int("POSTGRES_CONN_MAX_AGE", 120)  # noqa: F405
DATABASES["default"]["OPTIONS"]["sslmode"] = env.get("POSTGRES_SSLMODE", "prefer")  # noqa: F405

LOG_FORMAT = env.get("LOG_FORMAT", "json")
LOGGING["formatters"] = {  # noqa: F405
    "json": {
        "()": "apps.common.logging.JsonLogFormatter",
        "service": env.get("SERVICE_NAME", "carwash-api"),
    }
}
LOGGING["handlers"]["console"]["formatter"] = "json"  # noqa: F405

# Outbox worker concurrency is a separate process in production.
OUTBOX_BATCH_SIZE = env.get_int("OUTBOX_BATCH_SIZE", 100)

ALERT_EMAILS = env.get_list("ALERT_EMAILS", [])
if ALERT_EMAILS:
    ADMINS = [  # noqa: F405
        (entry.split(":", 1)[0].strip(), entry.split(":", 1)[1].strip())
        for entry in ALERT_EMAILS
        if ":" in entry
    ]