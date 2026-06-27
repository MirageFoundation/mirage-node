"""Media provider abstraction — base class, config, validation, and the
video resolution policy.

The node exposes ONE uniform upload contract (POST /api/upload_media). Behind
it, storage is pluggable via MEDIA_PROVIDER. This module holds the vendor-neutral
pieces shared by every provider; concrete providers live in local.py,
cloudflare.py, and bunny.py. No vendor name appears here.
"""

from __future__ import annotations

import os
from typing import Optional


class MediaError(Exception):
    """Structured error raised by the media layer.

    Carries a stable error code, a user-facing message, and an HTTP status so
    the route can translate it directly into an API error response.
    """

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


# ── Config (read at call time so tests/imports never hard-fail) ──────────────


def _int_env(key: str, default: int) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def short_clip_sec() -> int:
    """Clips at or under this duration are "short" (high-res allowed)."""
    return _int_env("MEDIA_SHORT_CLIP_SEC", 60)


def longform_max_height() -> int:
    """Max vertical resolution allowed for long-form (> short_clip_sec) video."""
    return _int_env("MEDIA_LONGFORM_MAX_HEIGHT", 1080)


def video_max_duration_sec() -> int:
    """Absolute hard cap on video duration regardless of resolution."""
    return _int_env("MEDIA_VIDEO_MAX_DURATION_SEC", 600)


def max_image_bytes() -> int:
    return _int_env("MEDIA_MAX_IMAGE_MB", 15) * 1024 * 1024


def max_video_bytes() -> int:
    return _int_env("MEDIA_MAX_VIDEO_MB", 300) * 1024 * 1024


# ── Magic-byte sniffing (never trust client content-type/filename) ───────────


# Map detected media to a canonical extension. Returns (kind, ext) or (None, None).
def sniff(data: bytes) -> tuple[Optional[str], Optional[str]]:
    if not data or len(data) < 12:
        return None, None
    head = data[:16]

    # Images
    if head[:3] == b"\xff\xd8\xff":
        return "image", ".jpg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image", ".png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image", ".gif"
    if head[:2] == b"BM":
        return "image", ".bmp"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image", ".webp"

    # ISO base media (ftyp) — disambiguate image (AVIF/HEIF) vs video (MP4/MOV)
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"avif", b"avis", b"heic", b"heix", b"mif1"):
            return "image", ".avif"
        if brand in (b"qt  ",):
            return "video", ".mov"
        # isom, mp41, mp42, iso2, iso5, dash, avc1, mp4v, ... -> mp4
        return "video", ".mp4"

    # Other video containers
    if head[:4] == b"\x1aE\xdf\xa3":
        return "video", ".webm"
    if head[:4] == b"OggS":
        return "video", ".ogv"

    return None, None


def validate_upload(kind: str, data: bytes, content_type: str | None) -> str:
    """Validate size + magic bytes for an upload. Returns the canonical
    extension. Raises MediaError on any problem.
    """
    if kind not in ("image", "video"):
        raise MediaError("media_invalid_kind", "kind must be 'image' or 'video'", 400)
    if not data:
        raise MediaError("media_file_required", "no file uploaded", 400)

    cap = max_image_bytes() if kind == "image" else max_video_bytes()
    if len(data) > cap:
        raise MediaError("media_too_large", "uploaded file is too large", 413)

    detected_kind, ext = sniff(data)
    if detected_kind is None:
        raise MediaError("media_invalid_type", "unsupported or unrecognized file type", 415)
    if detected_kind != kind:
        raise MediaError(
            "media_invalid_type",
            f"file content does not match kind '{kind}'",
            415,
        )
    return ext


def enforce_video_policy(transcodes: bool, duration: Optional[int], height: Optional[int]) -> None:
    """Apply the uniform video resolution policy. Raises MediaError on reject.

    - duration and height are required for video (probed client-side; the node
      has no transcoder for the local default).
    - duration > video_max_duration_sec -> reject (too long).
    - long-form (> short_clip_sec) above longform_max_height:
        - transcoding providers downscale via their encoding ladder (allowed).
        - non-transcoding providers cannot downscale -> reject.
    """
    if duration is None or height is None:
        raise MediaError(
            "media_metadata_required",
            "video duration and height are required",
            400,
        )
    if duration < 0 or height <= 0:
        raise MediaError("media_metadata_required", "invalid video metadata", 400)

    if duration > video_max_duration_sec():
        raise MediaError(
            "video_too_long",
            f"video is too long (max {video_max_duration_sec()}s)",
            400,
        )

    is_longform = duration > short_clip_sec()
    if is_longform and height > longform_max_height() and not transcodes:
        raise MediaError(
            "video_resolution_too_high",
            f"videos longer than {short_clip_sec()}s must be at most " f"{longform_max_height()}p on this node",
            400,
        )


class MediaProvider:
    """Base class for all storage providers.

    Concrete providers implement store/delete and the URL helpers. The uniform
    endpoint only ever calls store(); GC calls delete(); URL detection uses
    owns_url/asset_id_from_url/media_kind_for_url across the registry.
    """

    id: str = "base"
    transcodes: bool = False

    def store(
        self,
        kind: str,
        data: bytes,
        content_type: str | None,
        *,
        ext: str,
        duration: Optional[int] = None,
        height: Optional[int] = None,
    ) -> dict:
        """Persist bytes server-side and return {"url", "asset_id", "kind"}."""
        raise NotImplementedError

    def delete(self, asset_id: str) -> tuple[bool, str]:
        """Delete a stored asset. Returns (ok, detail)."""
        raise NotImplementedError

    def owns_url(self, url: str) -> bool:
        return False

    def asset_id_from_url(self, url: str) -> Optional[str]:
        return None

    def media_kind_for_url(self, url: str) -> Optional[str]:
        """Return 'image' | 'video' for a URL this provider owns, else None."""
        return None
