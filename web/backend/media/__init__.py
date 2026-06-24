"""Pluggable media providers.

One uniform upload contract (POST /api/upload_media) backed by a provider
selected via MEDIA_PROVIDER. This package exposes:

- get_media_provider(): the active provider (for store()).
- PROVIDER_REGISTRY: id -> class, the single extension point.
- resolve_url() / image_asset_id_from_url(): vendor-agnostic URL detection that
  consults ALL registered providers, so dual-read works for any past or future
  provider.
- validate_upload(), enforce_video_policy(), MediaError: shared upload logic.

Adding a provider = one subclass + one registry entry. No vendor name appears
outside its own provider module.
"""

from __future__ import annotations

import os
from typing import Optional

from media.base import (
    MediaError,
    MediaProvider,
    enforce_video_policy,
    longform_max_height,
    max_image_bytes,
    max_video_bytes,
    short_clip_sec,
    sniff,
    validate_upload,
    video_max_duration_sec,
)
from media.bunny import BunnyProvider
from media.cloudflare import CloudflareProvider
from media.local import LocalProvider

PROVIDER_REGISTRY: dict[str, type[MediaProvider]] = {
    "local": LocalProvider,
    "cloudflare": CloudflareProvider,
    "bunny": BunnyProvider,
}

_DEFAULT_PROVIDER = "local"

# Cache instances so URL detection doesn't reconstruct on every media URL.
_instances: dict[str, MediaProvider] = {}


def _instance(provider_id: str) -> MediaProvider:
    if provider_id not in _instances:
        _instances[provider_id] = PROVIDER_REGISTRY[provider_id]()
    return _instances[provider_id]


def active_provider_id() -> str:
    pid = os.environ.get("MEDIA_PROVIDER", _DEFAULT_PROVIDER).strip().lower() or _DEFAULT_PROVIDER
    if pid not in PROVIDER_REGISTRY:
        raise MediaError("media_unknown_provider", f"unknown MEDIA_PROVIDER '{pid}'", 500)
    return pid


def get_media_provider() -> MediaProvider:
    """Return the node's active storage provider."""
    return _instance(active_provider_id())


def all_providers() -> list[MediaProvider]:
    """Instances of every registered provider, for cross-provider URL detection.

    Construction never requires credentials (those are checked lazily in
    store()/delete()), so this is safe even when other providers are unconfigured.
    """
    return [_instance(pid) for pid in PROVIDER_REGISTRY]


def resolve_url(url: str) -> tuple[Optional[MediaProvider], Optional[str]]:
    """Find the provider that owns a URL and its asset id. (None, None) if none."""
    if not url:
        return None, None
    for provider in all_providers():
        try:
            if provider.owns_url(url):
                return provider, provider.asset_id_from_url(url)
        except Exception:
            continue
    return None, None


def image_asset_id_from_url(url: str) -> Optional[str]:
    """Return the catalog asset id for an image URL across all providers, else None."""
    if not url:
        return None
    for provider in all_providers():
        try:
            if provider.owns_url(url) and provider.media_kind_for_url(url) == "image":
                return provider.asset_id_from_url(url)
        except Exception:
            continue
    return None


__all__ = [
    "MediaError",
    "MediaProvider",
    "PROVIDER_REGISTRY",
    "get_media_provider",
    "active_provider_id",
    "all_providers",
    "resolve_url",
    "image_asset_id_from_url",
    "validate_upload",
    "enforce_video_policy",
    "sniff",
    "short_clip_sec",
    "longform_max_height",
    "video_max_duration_sec",
    "max_image_bytes",
    "max_video_bytes",
]
