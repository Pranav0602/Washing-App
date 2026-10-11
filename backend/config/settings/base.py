"""Base Django settings shared by every environment.

Environment-specific overrides live in ``dev``, ``test`` and ``prod``. Values come
exclusively from environment variables (see ``config.env``).
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from config import env

env.load_dotenv_if_present()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# --------------------------------------------------------------------------- core

SECRET_KEY = env.get("DJANGO_SECRET_KEY", "insecure-development-key-do-not-use-in-production")
DEBUG = env.get_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env.get_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1", "testserver"])

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
APPEND_SLASH = False

# The PDF requires all timestamps stored in UTC and rendered in the local zone.
TIME_ZONE = "UTC"
USE_TZ = True
USE_I18N = True
LANGUAGE_CODE = "en-us"

# Money is always integer minor units plus an explicit currency.
DEFAULT_CURRENCY = env.get("DEFAULT_CURRENCY", "INR")
PLATFORM_TIMEZONE = env.get("PLATFORM_TIMEZONE", "Asia/Kolkata")

# ----------------------------------------------------------------------- database

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env.get("POSTGRES_DB", "carwash"),
        "USER": env.get("POSTGRES_USER", "carwash"),
        "PASSWORD": env.get("POSTGRES_PASSWORD", ""),
        "HOST": env.get("POSTGRES_HOST", "localhost"),
        "PORT": env.get_int("POSTGRES_PORT", 5432),
        "CONN_MAX_AGE": env.get_int("POSTGRES_CONN_MAX_AGE", 60),
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            "connect_timeout": env.get_int("POSTGRES_CONNECT_TIMEOUT", 10),
        },
        "TEST": {
            "NAME": env.get("POSTGRES_TEST_DB", "test_carwash"),
        },
    }
}

# ----------------------------------------------------------------------- security

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_SECURE = env.get_bool("SESSION_COOKIE_SECURE", True)
CSRF_COOKIE_SECURE = env.get_bool("CSRF_COOKIE_SECURE", True)
CSRF_TRUSTED_ORIGINS = env.get_list("CSRF_TRUSTED_ORIGINS", [])
SECURE_HSTS_SECONDS = env.get_int("SECURE_HSTS_SECONDS", 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.get_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = env.get_bool("SECURE_HSTS_PRELOAD", False)
SECURE_SSL_REDIRECT = env.get_bool("SECURE_SSL_REDIRECT", False)

AUTH_USER_MODEL = "identity.User"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "django_filters",
    # Project modules. Order matters only for admin registration and migrations.
    "apps.common",
    "apps.identity",
    "apps.locations",
    "apps.catalog",
    "apps.quotes",
    "apps.partners",
    "apps.bookings",
    "apps.dispatch",
    "apps.evidence",
    "apps.payments",
    "apps.comms",
    "apps.notifications",
    "apps.support",
    "apps.webhooks",
    "apps.ops",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Project middleware
    "apps.common.middleware.RequestIdMiddleware",
    "apps.common.middleware.RequestAuditMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

# ------------------------------------------------------------------- rest framework

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.identity.authentication.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["apps.common.permissions.IsAuthenticatedActor"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "EXCEPTION_HANDLER": "apps.common.exceptions.api_exception_handler",
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.DefaultPagination",
    "PAGE_SIZE": env.get_int("API_DEFAULT_PAGE_SIZE", 20),
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "DEFAULT_THROTTLE_CLASSES": [
        "apps.common.throttling.BurstThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "otp_request": env.get("RATE_LIMIT_OTP_REQUEST", "5/15min"),
        "otp_verify": env.get("RATE_LIMIT_OTP_VERIFY", "10/15min"),
        "quote": env.get("RATE_LIMIT_QUOTE", "30/min"),
        "booking": env.get("RATE_LIMIT_BOOKING", "10/hour"),
        "location": env.get("RATE_LIMIT_LOCATION", "60/min"),
        "evidence": env.get("RATE_LIMIT_EVIDENCE", "40/hour"),
        "comms": env.get("RATE_LIMIT_COMMS", "60/5min"),
        "ops_write": env.get("RATE_LIMIT_OPS_WRITE", "120/min"),
    },
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

# ------------------------------------------------------------------- authentication

JWT_SIGNING_KEY = env.get("JWT_SIGNING_KEY", SECRET_KEY)
JWT_ALGORITHM = "HS256"
JWT_ISSUER = env.get("JWT_ISSUER", "carwash")
JWT_AUDIENCE = env.get("JWT_AUDIENCE", "carwash-mobile")
JWT_ACCESS_TTL = timedelta(minutes=env.get_int("JWT_ACCESS_TTL_MINUTES", 15))
JWT_REFRESH_TTL = timedelta(days=env.get_int("JWT_REFRESH_TTL_DAYS", 30))
JWT_LEEWAY_SECONDS = env.get_int("JWT_LEEWAY_SECONDS", 30)

OTP_PEPPER = env.get("OTP_PEPPER", "development-otp-pepper")
OTP_TTL_SECONDS = env.get_int("OTP_TTL_SECONDS", 300)
OTP_MAX_ATTEMPTS = env.get_int("OTP_MAX_ATTEMPTS", 5)
OTP_RESEND_COOLDOWN_SECONDS = env.get_int("OTP_RESEND_COOLDOWN_SECONDS", 60)
OTP_LENGTH = env.get_int("OTP_LENGTH", 6)

IDEMPOTENCY_TTL_HOURS = env.get_int("IDEMPOTENCY_TTL_HOURS", 24)

# -------------------------------------------------------------------------- cors

CORS_ALLOWED_ORIGINS = env.get_list("CORS_ALLOWED_ORIGINS", [])
CORS_ALLOW_HEADERS = [
    "accept",
    "authorization",
    "content-type",
    "idempotency-key",
    "origin",
    "user-agent",
    "x-request-id",
    "x-client",
    "x-platform",
]
CORS_ALLOW_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]

# ------------------------------------------------------------------- static files

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = "media/"
MEDIA_ROOT = env.get("MEDIA_ROOT", str(BASE_DIR / "var" / "media"))

# -------------------------------------------------------------------- integrations

EVIDENCE_STORAGE_BACKEND = env.get_choice(
    "EVIDENCE_STORAGE_BACKEND", ("filesystem",), "filesystem"
)
EVIDENCE_ROOT = env.get("EVIDENCE_ROOT", str(BASE_DIR / "var" / "evidence"))
EVIDENCE_MAX_UPLOAD_BYTES = env.get_int("EVIDENCE_MAX_UPLOAD_BYTES", 10 * 1024 * 1024)
EVIDENCE_RETENTION_DAYS = env.get_int("EVIDENCE_RETENTION_DAYS", 180)
EVIDENCE_SIGNED_URL_TTL_SECONDS = env.get_int("EVIDENCE_SIGNED_URL_TTL_SECONDS", 300)

PAYMENT_GATEWAY = env.get_choice(
    "PAYMENT_GATEWAY", ("sandbox", "noop"), "sandbox"
)
PAYMENT_WEBHOOK_SECRET = env.get("PAYMENT_WEBHOOK_SECRET", "development-webhook-secret")
PAYMENT_AUTHORIZATION_WINDOW_HOURS = env.get_int("PAYMENT_AUTHORIZATION_WINDOW_HOURS", 72)
PAYMENT_CAPTURE_METHOD = env.get_choice(
    "PAYMENT_CAPTURE_METHOD", ("on_completion",), "on_completion"
)
PLATFORM_FEE_BPS = env.get_int("PLATFORM_FEE_BPS", 1500)
TAX_BPS = env.get_int("TAX_BPS", 0)
REFUND_APPROVAL_LIMIT_MINOR = env.get_int("REFUND_APPROVAL_LIMIT_MINOR", 500000)

# Cancellation policy. These are configuration, not code, and the resulting snapshot
# is stored on each booking so a later change cannot retroactively apply.
TERMS_VERSION = env.get("TERMS_VERSION", "2026-10-01")
CANCELLATION_FREE_WINDOW_HOURS = env.get_int("CANCELLATION_FREE_WINDOW_HOURS", 4)
CANCELLATION_LATE_FEE_BPS = env.get_int("CANCELLATION_LATE_FEE_BPS", 1000)
CANCELLATION_NO_SHOW_FEE_BPS = env.get_int("CANCELLATION_NO_SHOW_FEE_BPS", 0)

PUSH_PROVIDER = env.get_choice("PUSH_PROVIDER", ("expo", "noop"), "noop")
EXPO_PUSH_ENABLED = env.get_bool("EXPO_PUSH_ENABLED", False)
EXPO_PUSH_ACCESS_TOKEN = env.get("EXPO_PUSH_ACCESS_TOKEN", "")

ETA_PROVIDER = env.get_choice("ETA_PROVIDER", ("estimate", "noop"), "estimate")
ETA_ASSUMED_SPEED_KMH = env.get_float("ETA_ASSUMED_SPEED_KMH", 22.0)
ETA_TRAFFIC_FACTOR = env.get_float("ETA_TRAFFIC_FACTOR", 1.35)

COMMS_PROVIDER = env.get_choice("COMMS_PROVIDER", ("relay", "noop"), "relay")
COMMUNICATION_WINDOW_MINUTES = env.get_int("COMMUNICATION_WINDOW_MINUTES", 120)

# ------------------------------------------------------------------------ dispatch

DISPATCH_OFFER_TTL_SECONDS = env.get_int("DISPATCH_OFFER_TTL_SECONDS", 120)
DISPATCH_OFFER_BATCH_SIZE = env.get_int("DISPATCH_OFFER_BATCH_SIZE", 3)
DISPATCH_MAX_ROUNDS = env.get_int("DISPATCH_MAX_ROUNDS", 5)
DISPATCH_DEFAULT_TRAVEL_LIMIT_KM = env.get_float("DISPATCH_DEFAULT_TRAVEL_LIMIT_KM", 12.0)
DISPATCH_ARRIVAL_PROMISE_MINUTES = env.get_int("DISPATCH_ARRIVAL_PROMISE_MINUTES", 30)
DISPATCH_STALE_LOCATION_SECONDS = env.get_int("DISPATCH_STALE_LOCATION_SECONDS", 300)
DISPATCH_MILESTONE_GRACE_MINUTES = env.get_int("DISPATCH_MILESTONE_GRACE_MINUTES", 20)
DISPATCH_FAIRNESS_WEIGHT = env.get_float("DISPATCH_FAIRNESS_WEIGHT", 0.25)
DISPATCH_ETA_WEIGHT = env.get_float("DISPATCH_ETA_WEIGHT", 1.0)
DISPATCH_RELIABILITY_WEIGHT = env.get_float("DISPATCH_RELIABILITY_WEIGHT", 0.5)

LOCATION_PING_RETENTION_HOURS = env.get_int("LOCATION_PING_RETENTION_HOURS", 24)
LOCATION_PING_MAX_ACCURACY_M = env.get_float("LOCATION_PING_MAX_ACCURACY_M", 200.0)

# ------------------------------------------------------------------------- outbox

OUTBOX_MAX_ATTEMPTS = env.get_int("OUTBOX_MAX_ATTEMPTS", 6)
OUTBOX_BATCH_SIZE = env.get_int("OUTBOX_BATCH_SIZE", 50)
OUTBOX_LOCK_TIMEOUT_SECONDS = env.get_int("OUTBOX_LOCK_TIMEOUT_SECONDS", 300)

# ------------------------------------------------------------------- notifications

NOTIFICATION_RETENTION_DAYS = env.get_int("NOTIFICATION_RETENTION_DAYS", 30)

# ------------------------------------------------------------------------ logging

LOG_LEVEL = env.get("LOG_LEVEL", "INFO")
LOG_FORMAT = env.get("LOG_FORMAT", "plain")
SERVICE_NAME = env.get("SERVICE_NAME", "carwash-api")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
        "json": {
            "()": "apps.common.logging.JsonLogFormatter",
            "service": env.get("SERVICE_NAME", "carwash-api"),
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json" if LOG_FORMAT == "json" else "plain",
        }
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.db.backends": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "apps": {"level": LOG_LEVEL, "handlers": ["console"], "propagate": False},
    },
}

SILENCED_SYSTEM_CHECKS: list[str] = []

DATA_UPLOAD_MAX_MEMORY_SIZE = EVIDENCE_MAX_UPLOAD_BYTES * 2
FILE_UPLOAD_MAX_MEMORY_SIZE = EVIDENCE_MAX_UPLOAD_BYTES