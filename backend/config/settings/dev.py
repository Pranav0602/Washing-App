"""Development settings: verbose, human-readable logs, local integrations."""

from __future__ import annotations

from config import env
from config.settings.base import *  # noqa: F403

DEBUG = env.get_bool("DJANGO_DEBUG", True)

INTERNAL_IPS = ["127.0.0.1"]

EMAIL_BACKEND = env.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env.get("DEFAULT_FROM_EMAIL", "no-reply@carwash.local")

# Local Expo dev server origins.
CORS_ALLOWED_ORIGINS = env.get_list(
    "CORS_ALLOWED_ORIGINS",
    ["http://localhost:8081", "http://localhost:19006", "http://127.0.0.1:8081"],
)

# Cookies only need to be secure when served over TLS, which local dev is not.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]