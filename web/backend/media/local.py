"""Local on-disk media provider (default for new nodes).

Stores uploads on the node's own persistent volume and serves them via Caddy's
/media/* file_server. No third-party account, runs instantly. Cannot transcode,
so it rejects long-form video above the resolution cap (enforced upstream).
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse
from uuid import uuid4

from media.base import MediaProvider

_REL_RE = re.compile(r"^(images|videos)/\d{4}/\d{2}/[0-9a-f]{32}\.[a-z0-9]{1,5}$")


class LocalProvider(MediaProvider):
    id = "local"
    transcodes = False

    def __init__(self):
        self.root = os.environ.get("MEDIA_LOCAL_DIR", "").strip() or os.path.expanduser("~/.mirage/media")
        # Empty base -> relative "/media/..." (served by the same origin via Caddy).
        self.base_url = os.environ.get("MEDIA_PUBLIC_BASE_URL", "").strip().rstrip("/")

    def _rel_path(self, kind: str, ext: str) -> str:
        sub = "images" if kind == "image" else "videos"
        now = datetime.now(timezone.utc)
        return f"{sub}/{now:%Y/%m}/{uuid4().hex}{ext}"

    def _abs_path(self, rel: str) -> Optional[str]:
        # Guard against path traversal: the resolved path must stay under root.
        root = os.path.realpath(self.root)
        candidate = os.path.realpath(os.path.join(root, rel))
        if candidate != root and not candidate.startswith(root + os.sep):
            return None
        return candidate

    def store(self, kind, data, content_type, *, ext, duration=None, height=None) -> dict:
        rel = self._rel_path(kind, ext)
        path = self._abs_path(rel)
        if path is None:
            raise RuntimeError("computed media path escaped root")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
        url = f"{self.base_url}/media/{rel}" if self.base_url else f"/media/{rel}"
        return {"url": url, "asset_id": rel, "kind": kind}

    def delete(self, asset_id: str) -> tuple[bool, str]:
        if not _REL_RE.match(asset_id or ""):
            return False, "invalid_asset_id"
        path = self._abs_path(asset_id)
        if path is None:
            return False, "invalid_asset_id"
        try:
            os.remove(path)
            return True, ""
        except FileNotFoundError:
            return True, "already_gone"
        except Exception as e:  # noqa: BLE001 - surface detail to GC log
            return False, str(e)

    def _rel_from_url(self, url: str) -> Optional[str]:
        try:
            path = urlparse(url).path or ""
        except Exception:
            return None
        if "/media/" not in path:
            return None
        rel = path.split("/media/", 1)[1]
        return rel if _REL_RE.match(rel) else None

    def owns_url(self, url: str) -> bool:
        if not url:
            return False
        # Reject other providers' absolute hosts; accept relative or our base_url.
        try:
            host = (urlparse(url).hostname or "").lower()
        except Exception:
            return False
        if host:
            base_host = (urlparse(self.base_url).hostname or "").lower() if self.base_url else ""
            if not base_host or host != base_host:
                return False
        return self._rel_from_url(url) is not None

    def asset_id_from_url(self, url: str) -> Optional[str]:
        if not self.owns_url(url):
            return None
        return self._rel_from_url(url)

    def media_kind_for_url(self, url: str) -> Optional[str]:
        rel = self.asset_id_from_url(url)
        if not rel:
            return None
        return "image" if rel.startswith("images/") else "video"
