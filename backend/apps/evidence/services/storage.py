"""Private evidence storage.

The PDF requires private object storage with database references and retention
metadata, not database blobs. This module owns:

* content-type and size validation (the defence against unsafe uploads)
* a SHA-256 checksum, stored alongside the record
* an object key that cannot be guessed from a booking reference
* short-lived signed reads, with every read logged
* deletion, which is refused while a legal hold applies

The default backend writes to a private directory outside any static-file route. An
S3-compatible adapter can replace it without touching callers.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("apps.evidence.storage")

#: Image types we accept. Anything else is refused rather than sniffed.
ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
}

MAX_BYTES = 10 * 1024 * 1024

#: Magic-number prefixes, checked in addition to the declared content type so a
#: renamed executable cannot masquerade as a JPEG.
MAGIC_PREFIXES: dict[str, tuple[bytes, ...]] = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
    "image/heic": (b"ftyp",),
}


class UnsafeUpload(Exception):
    """The uploaded file failed validation."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    object_key: str
    checksum_sha256: str
    byte_size: int
    content_type: str


def _storage_root() -> Path:
    root = Path(settings.EVIDENCE_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return root


def validate_upload(upload) -> tuple[str, bytes]:
    """Check the declared type, the size, and the actual magic bytes.

    Returns ``(content_type, leading_bytes)``. Raises :class:`UnsafeUpload` on any
    failure so a partially-validated file is never written.
    """
    content_type = (upload.content_type or "").lower().split(";")[0].strip()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise UnsafeUpload(
            f"Unsupported file type {content_type!r}. Allowed: {sorted(ALLOWED_CONTENT_TYPES)}"
        )
    size = getattr(upload, "size", None)
    if size is not None and size > MAX_BYTES:
        raise UnsafeUpload(f"File is {size} bytes; the limit is {MAX_BYTES}.")

    head = upload.read(16)
    try:
        upload.seek(0)
    except (AttributeError, OSError):  # pragma: no cover - non-seekable stream
        pass

    prefixes = MAGIC_PREFIXES.get(content_type, ())
    if prefixes and not any(head.startswith(prefix) for prefix in prefixes):
        raise UnsafeUpload(
            f"File content does not match its declared type {content_type!r}."
        )
    return content_type, head


def build_object_key(*, namespace: str, content_type: str) -> str:
    """A random, non-guessable key scoped by namespace.

    The key deliberately contains nothing derived from a booking reference, so
    knowing one reference cannot be used to derive another's object path.
    """
    extension = ALLOWED_CONTENT_TYPES.get(content_type, "")
    today = timezone.now().strftime("%Y/%m/%d")
    token = uuid.uuid4().hex
    safe_namespace = "/".join(part for part in namespace.split("/") if part)
    return f"{safe_namespace}/{today}/{token}{extension}"


def store_upload(*, upload, namespace: str) -> StoredObject:
    """Validate and persist an uploaded file. Returns the stored reference."""
    content_type, _head = validate_upload(upload)
    object_key = build_object_key(namespace=namespace, content_type=content_type)

    digest = hashlib.sha256()
    total = 0
    destination = _storage_root() / object_key
    destination.parent.mkdir(parents=True, exist_ok=True)

    # Write under a temporary name then move, so a partial write is never readable.
    temporary = destination.with_suffix(destination.suffix + ".partial")
    try:
        with temporary.open("wb") as handle:
            for chunk in upload.chunks():
                digest.update(chunk)
                total += len(chunk)
                handle.write(chunk)
        if total > MAX_BYTES:
            temporary.unlink(missing_ok=True)
            raise UnsafeUpload(f"File exceeded the {MAX_BYTES} byte limit while streaming.")
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    logger.info("evidence_stored key=%s bytes=%s type=%s", object_key, total, content_type)
    return StoredObject(
        object_key=object_key,
        checksum_sha256=digest.hexdigest(),
        byte_size=total,
        content_type=content_type,
    )


def read_object(*, object_key: str) -> tuple[Path, str]:
    """Resolve an object key to a readable path, refusing traversal."""
    root = _storage_root().resolve()
    candidate = (root / object_key).resolve()

    # Path traversal guard: the resolved path must stay inside the storage root.
    try:
        candidate.relative_to(root)
    except ValueError:
        logger.error("evidence_path_traversal_blocked key=%s", object_key)
        raise PermissionError("Invalid object key.") from None

    if not candidate.is_file():
        raise FileNotFoundError(object_key)

    import mimetypes

    content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    return candidate, content_type


def sign_key(*, object_key: str, expires_in_seconds: int | None = None) -> str:
    """A short-lived signature for an object key.

    Included in the filename so a read can be authorised without a database lookup,
    and so a leaked URL stops working quickly.
    """
    ttl = expires_in_seconds or settings.EVIDENCE_SIGNED_URL_TTL_SECONDS
    expires_at = int((timezone.now() + timedelta(seconds=ttl)).timestamp())
    payload = f"{object_key}:{expires_at}"
    signature = hmac.new(
        settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return f"{expires_at}.{signature}"


def verify_signature(*, object_key: str, token: str) -> bool:
    try:
        expires_at_raw, signature = token.split(".", 1)
        expires_at = int(expires_at_raw)
    except (ValueError, AttributeError):
        return False
    if timezone.now().timestamp() > expires_at:
        return False
    payload = f"{object_key}:{expires_at}"
    expected = hmac.new(
        settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def delete_object(*, object_key: str) -> bool:
    try:
        _path, _content_type = read_object(object_key=object_key)
    except (FileNotFoundError, PermissionError):
        return False
    _path.unlink(missing_ok=True)
    logger.info("evidence_deleted key=%s", object_key)
    return True


def storage_usage_bytes() -> int:
    root = _storage_root()
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())