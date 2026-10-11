"""ASGI entrypoint.

WebSockets are not implemented for the pilot: active-job updates use push plus
polling, which the PDF requires as the fallback anyway. This entrypoint exists so
a WebSocket layer can be added without changing the deployment shape.
"""

from __future__ import annotations

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_asgi_application()