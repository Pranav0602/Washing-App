"""End-to-end smoke test of the authentication flow against a real database.

Run with:  python manage.py shell < scripts/smoke_auth.py
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

# Allow running the file directly: put the backend root on the import path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

from django.test import Client  # noqa: E402

FAILURES: list[str] = []


def fresh_phone() -> str:
    """A unique 10-digit number so repeated runs never trip the resend cooldown."""
    return f"9{secrets.randbelow(10**8):08d}"


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}{(' - ' + detail) if detail else ''}")
    if not condition:
        FAILURES.append(label)


def main() -> int:
    client = Client()
    primary_phone = fresh_phone()

    # 1. request an OTP
    response = client.post(
        "/api/v1/auth/otp/request",
        data={"phone": primary_phone, "purpose": "login"},
        content_type="application/json",
    )
    check("OTP request returns 202", response.status_code == 202, f"got {response.status_code}")
    if response.status_code != 202:
        print(response.content[:400])
        return 1
    body = response.json()
    challenge_id = body["challenge_id"]
    check("challenge id returned", bool(challenge_id))
    check("request id echoed", "X-Request-Id" in response.headers)
    check("expires_at present", "expires_at" in body)

    # 2. resend inside the cooldown must be refused
    resend = client.post(
        "/api/v1/auth/otp/resend",
        data={"challenge_id": challenge_id},
        content_type="application/json",
    )
    check("resend inside cooldown is 429", resend.status_code == 429, f"got {resend.status_code}")
    if resend.status_code == 429:
        check(
            "cooldown error code is stable",
            resend.json()["error"]["code"] == "otp_resend_too_soon",
            resend.json()["error"]["code"],
        )

    # 3. wrong code must fail with attempts remaining
    from apps.identity.models import OtpChallenge

    wrong = client.post(
        "/api/v1/auth/otp/verify",
        data={"challenge_id": challenge_id, "code": "000000"},
        content_type="application/json",
    )
    check("wrong code is 400", wrong.status_code == 400, f"got {wrong.status_code}")
    check(
        "wrong code error code",
        wrong.json()["error"]["code"] == "invalid_otp_code",
        wrong.json()["error"]["code"],
    )
    check("attempts_remaining reported", wrong.json()["error"]["details"].get("attempts_remaining") == 4)

    # 4. correct code issues tokens
    correct = client.post(
        "/api/v1/auth/otp/verify",
        data={"challenge_id": challenge_id, "code": "123456"},
        content_type="application/json",
    )
    check("unknown code rejected", correct.status_code == 400, f"got {correct.status_code}")

    # Issue a known-good code directly for the happy path, on a fresh number so the
    # resend cooldown from step 2 does not interfere.
    from apps.identity.services import otp as otp_service

    issued = otp_service.request_challenge(
        raw_phone=fresh_phone(), purpose="login", deliver=lambda phone, code: None
    )
    happy = client.post(
        "/api/v1/auth/otp/verify",
        data={"challenge_id": str(issued.challenge.pk), "code": issued.code},
        content_type="application/json",
    )
    check("valid code returns 200", happy.status_code == 200, f"got {happy.status_code}")
    if happy.status_code != 200:
        print(happy.content[:500])
        return 1

    payload = happy.json()
    check("access token issued", bool(payload["access_token"]))
    check("refresh token issued", bool(payload["refresh_token"]))
    check("new user created", payload["user"]["roles"] == [], str(payload["user"]["roles"]))
    check("next step is register_customer", payload["next"] == "register_customer", payload["next"])

    # 5. the token works on a protected endpoint
    auth = {"HTTP_AUTHORIZATION": f"Bearer {payload['access_token']}"}
    me = client.get("/api/v1/me", **auth)
    check("authenticated /me returns 200", me.status_code == 200, f"got {me.status_code}")

    # 6. no token is rejected
    anon = client.get("/api/v1/me")
    check("anonymous /me is 401", anon.status_code == 401, f"got {anon.status_code}")
    check(
        "401 uses the error envelope",
        anon.json().get("error", {}).get("code") == "unauthenticated",
        str(anon.json())[:120],
    )

    # 7. refresh rotation
    refreshed = client.post(
        "/api/v1/auth/refresh",
        data={"refresh_token": payload["refresh_token"]},
        content_type="application/json",
    )
    check("refresh returns 200", refreshed.status_code == 200, f"got {refreshed.status_code}")
    new_refresh = refreshed.json()["refresh_token"]
    check("refresh rotated the token", new_refresh != payload["refresh_token"])

    # 8. replaying the old refresh token must revoke the family
    replay = client.post(
        "/api/v1/auth/refresh",
        data={"refresh_token": payload["refresh_token"]},
        content_type="application/json",
    )
    check("replayed refresh token is 401", replay.status_code == 401, f"got {replay.status_code}")

    after_replay = client.post(
        "/api/v1/auth/refresh",
        data={"refresh_token": new_refresh},
        content_type="application/json",
    )
    check(
        "family revoked after replay",
        after_replay.status_code == 401,
        f"got {after_replay.status_code}",
    )

    # 9. health probes
    check("health is 200", client.get("/health/").status_code == 200)
    check("ready is 200", client.get("/ready/").status_code == 200)

    # 10. the code is never stored in plaintext
    stored = OtpChallenge.objects.filter(pk=issued.challenge.pk).first()
    check(
        "otp stored hashed",
        stored is None or stored.code_hash != issued.code,
    )
    check(
        "otp hash is peppered sha256",
        stored is not None and len(stored.code_hash) == 64,
    )

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {', '.join(FAILURES)}")
        return 1
    print("all authentication smoke checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())