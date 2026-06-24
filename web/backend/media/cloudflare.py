"""Cloudflare media provider — server-side upload to Cloudflare Images/Stream.

Uploads bytes through the Cloudflare API (NOT browser-direct) so it sits behind
the same uniform endpoint as every other provider. Delivery uses the existing
imagedelivery.net / videodelivery.net hosts, so previously stored Cloudflare
media keeps working (dual-read).
"""

from __future__ import annotations

import os
import re
from typing import Optional
from urllib.parse import urlparse

import requests

from media.base import MediaError, MediaProvider

_CF_API = "https://api.cloudflare.com/client/v4"
_IMAGE_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


class CloudflareProvider(MediaProvider):
    id = "cloudflare"
    transcodes = True

    def __init__(self):
        self.account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
        self.api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
        self.account_hash = os.environ.get("CLOUDFLARE_ACCOUNT_HASH", "").strip()

    def _require_creds(self, need_hash: bool = False) -> None:
        if not self.account_id or not self.api_token or (need_hash and not self.account_hash):
            raise MediaError(
                "media_provider_not_configured",
                "cloudflare credentials not configured",
                500,
            )

    def store(self, kind, data, content_type, *, ext, duration=None, height=None) -> dict:
        if kind == "image":
            return self._store_image(data, content_type, ext)
        return self._store_video(data, content_type, ext)

    def _store_image(self, data: bytes, content_type: str | None, ext: str) -> dict:
        self._require_creds(need_hash=True)
        url = f"{_CF_API}/accounts/{self.account_id}/images/v1"
        headers = {"Authorization": f"Bearer {self.api_token}"}
        files = {"file": (f"upload{ext}", data, content_type or "application/octet-stream")}
        resp = requests.post(url, headers=headers, files=files, timeout=60)
        if resp.status_code != 200:
            raise MediaError("media_store_failed", "image upload service error", 502)
        result = (resp.json() or {}).get("result", {})
        image_id = (result.get("id") or "").strip()
        if not image_id:
            raise MediaError("media_store_failed", "no image id returned", 502)
        delivery = f"https://imagedelivery.net/{self.account_hash}/{image_id}/public"
        return {"url": delivery, "asset_id": image_id.lower(), "kind": "image"}

    def _store_video(self, data: bytes, content_type: str | None, ext: str) -> dict:
        self._require_creds()
        url = f"{_CF_API}/accounts/{self.account_id}/stream"
        headers = {"Authorization": f"Bearer {self.api_token}"}
        files = {"file": (f"video{ext}", data, content_type or "video/mp4")}
        resp = requests.post(url, headers=headers, files=files, timeout=180)
        if resp.status_code != 200:
            raise MediaError("media_store_failed", "video upload service error", 502)
        result = (resp.json() or {}).get("result", {})
        uid = (result.get("uid") or "").strip()
        if not uid:
            raise MediaError("media_store_failed", "no video uid returned", 502)
        return {
            "url": f"https://videodelivery.net/{uid}/manifest/video.m3u8",
            "asset_id": uid,
            "kind": "video",
        }

    def delete(self, asset_id: str) -> tuple[bool, str]:
        # GC only tracks images; image ids are uuids.
        if not _IMAGE_ID_RE.match(asset_id or ""):
            return False, "not_an_image_id"
        if not self.account_id or not self.api_token:
            return False, "cloudflare credentials not configured"
        url = f"{_CF_API}/accounts/{self.account_id}/images/v1/{asset_id}"
        headers = {"Authorization": f"Bearer {self.api_token}"}
        try:
            resp = requests.delete(url, headers=headers, timeout=15)
            if resp.status_code == 200:
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
        return (
            host.endswith("imagedelivery.net")
            or host.endswith("videodelivery.net")
            or host.endswith("cloudflarestream.com")
        )

    def asset_id_from_url(self, url: str) -> Optional[str]:
        host = self._host(url)
        try:
            parts = [p for p in (urlparse(url).path or "").split("/") if p]
        except Exception:
            return None
        if host.endswith("imagedelivery.net"):
            if len(parts) >= 2 and _IMAGE_ID_RE.match(parts[1]):
                return parts[1].lower()
            return None
        if host.endswith("videodelivery.net") or host.endswith("cloudflarestream.com"):
            if parts and re.fullmatch(r"[a-z0-9]+", parts[0]):
                return parts[0]
        return None

    def media_kind_for_url(self, url: str) -> Optional[str]:
        host = self._host(url)
        if host.endswith("imagedelivery.net"):
            return "image"
        if host.endswith("videodelivery.net") or host.endswith("cloudflarestream.com"):
            return "video"
        return None
