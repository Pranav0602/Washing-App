"""Push notification provider port."""

from __future__ import annotations

from typing import Protocol

from django.conf import settings


class PushProvider(Protocol):
    name: str

    def send(self, *, token: str, title: str, body: str, data: dict) -> None: ...


class ExpoPushProvider:
    """Expo push transport.

    Uses the HTTP API directly so no extra SDK dependency is introduced.
    """

    name = "expo"
    ENDPOINT = "https://exp.host/--/api/v2/push/send"

    def __init__(self) -> None:
        import json
        import urllib.request

        self._json = json
        self._urlopen = urllib.request.urlopen

    def send(self, *, token: str, title: str, body: str, data: dict) -> None:
        payload = self._json.dumps(
            {
                "to": token,
                "title": title,
                "body": body,
                "data": data,
                "sound": "default",
                "priority": "high",
            }
        ).encode()

        request = self._urlopen(
            self.ENDPOINT,
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=10,
        )
        with request:
            result = self._json.loads(request.read().decode())

        # Expo reports per-message errors inside a 200 response.
        if isinstance(result, dict) and result.get("errors"):
            raise RuntimeError(f"Expo push error: {result['errors']}")


class NoopPushProvider:
    name = "noop"

    def send(self, **kwargs) -> None:
        return None


def get_push_provider() -> PushProvider:
    key = getattr(settings, "PUSH_PROVIDER", "noop")
    return {"expo": ExpoPushProvider, "noop": NoopPushProvider}.get(key, NoopPushProvider)()