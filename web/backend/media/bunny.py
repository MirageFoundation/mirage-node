"""Bunny media provider — server-side upload to Bunny Storage + Bunny Stream.

Images go to a Bunny Storage zone and are delivered through an Optimizer-enabled
pull zone. Video goes to a Bunny Stream library (which transcodes an HLS ladder)
and is delivered via the library's CDN host.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse
from uuid import uuid4

import requests

from media.base import MediaError, MediaProvider

_IMG_REL_RE = re.compile(r"^images/\d{4}/\d{2}/[0-9a-f]{32}\.[a-z0-9]{1,5}$")
_GUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")


class BunnyProvider(MediaProvider):
    id = "bunny"
    transcodes = True

    def __init__(self):
        # Storage (images)
        self.storage_zone = os.environ.get("BUNNY_STORAGE_ZONE", "").strip()
        self.storage_key = os.environ.get("BUNNY_STORAGE_ACCESS_KEY", "").strip()
        self.storage_host = os.environ.get("BUNNY_STORAGE_HOST", "storage.bunnycdn.com").strip()
        self.pull_zone_host = os.environ.get("BUNNY_PULL_ZONE_HOST", "").strip().lower()
        # Stream (video)
        self.stream_library = os.environ.get("BUNNY_STREAM_LIBRARY_ID", "").strip()
        self.stream_key = os.environ.get("BUNNY_STREAM_API_KEY", "").strip()
        self.stream_cdn_host = os.environ.get("BUNNY_STREAM_CDN_HOST", "").strip().lower()

    # ── Images via Bunny Storage ────────────────────────────────────────────
    def _store_image(self, data: bytes, content_type: str | None, ext: str) -> dict:
        if not self.storage_zone or not self.storage_key or not self.pull_zone_host:
            raise MediaError("media_provider_not_configured", "bunny storage not configured", 500)
        now = datetime.now(timezone.utc)
        rel = f"images/{now:%Y/%m}/{uuid4().hex}{ext}"
        url = f"https://{self.storage_host}/{self.storage_zone}/{rel}"
        headers = {
            "AccessKey": self.storage_key,
            "Content-Type": content_type or "application/octet-stream",
        }
        resp = requests.put(url, headers=headers, data=data, timeout=60)
        if resp.status_code not in (200, 201):
            raise MediaError("media_store_failed", "image upload service error", 502)
        delivery = f"https://{self.pull_zone_host}/{rel}"
        return {"url": delivery, "asset_id": rel, "kind": "image"}

    # ── Video via Bunny Stream ──────────────────────────────────────────────
    def _store_video(self, data: bytes, content_type: str | None, ext: str) -> dict:
        if not self.stream_library or not self.stream_key or not self.stream_cdn_host:
            raise MediaError("media_provider_not_configured", "bunny stream not configured", 500)
        base = f"https://video.bunnycdn.com/library/{self.stream_library}/videos"
        headers = {"AccessKey": self.stream_key}
        create = requests.post(
            base,
            headers={**headers, "Content-Type": "application/json"},
            json={"title": uuid4().hex},
            timeout=30,
        )
        if create.status_code not in (200, 201):
            raise MediaError("media_store_failed", "video create service error", 502)
        guid = ((create.json() or {}).get("guid") or "").strip()
        if not guid:
            raise MediaError("media_store_failed", "no video guid returned", 502)
        upload = requests.put(
            f"{base}/{guid}",
            headers={**headers, "Content-Type": "application/octet-stream"},
            data=data,
            timeout=180,
        )
        if upload.status_code not in (200, 201):
            raise MediaError("media_store_failed", "video upload service error", 502)
        delivery = f"https://{self.stream_cdn_host}/{guid}/playlist.m3u8"
        return {"url": delivery, "asset_id": guid, "kind": "video"}

    def store(self, kind, data, content_type, *, ext, duration=None, height=None) -> dict:
        if kind == "image":
            return self._store_image(data, content_type, ext)
        return self._store_video(data, content_type, ext)

    def delete(self, asset_id: str) -> tuple[bool, str]:
        # GC only tracks images; image asset ids are storage-relative paths.
        if not _IMG_REL_RE.match(asset_id or ""):
            return False, "not_an_image_id"
        if not self.storage_zone or not self.storage_key:
            return False, "bunny storage not configured"
        url = f"https://{self.storage_host}/{self.storage_zone}/{asset_id}"
        try:
            resp = requests.delete(url, headers={"AccessKey": self.storage_key}, timeout=15)
            if resp.status_code in (200, 204):
                return True, ""
            if resp.status_code == 404:
                return True, "already_gone"
            return False, f"status={resp.status_code} body={resp.text[:200]}"
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    def _host(self, url: str) -> str:
        try:
            return (urlparse(url).hostname or "").lower()
        except Exception:
            return ""

    def owns_url(self, url: str) -> bool:
        host = self._host(url)
        if not host:
            return False
        return (self.pull_zone_host and host == self.pull_zone_host) or (
            self.stream_cdn_host and host == self.stream_cdn_host
        )

    def asset_id_from_url(self, url: str) -> Optional[str]:
        host = self._host(url)
        try:
            parts = [p for p in (urlparse(url).path or "").split("/") if p]
        except Exception:
            return None
        if self.pull_zone_host and host == self.pull_zone_host:
            rel = "/".join(parts)
            return rel if _IMG_REL_RE.match(rel) else None
        if self.stream_cdn_host and host == self.stream_cdn_host:
            if parts and _GUID_RE.match(parts[0]):
                return parts[0]
        return None

    def media_kind_for_url(self, url: str) -> Optional[str]:
        host = self._host(url)
        if self.pull_zone_host and host == self.pull_zone_host:
            return "image"
        if self.stream_cdn_host and host == self.stream_cdn_host:
            return "video"
        return None
