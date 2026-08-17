"""RedGIFs thumbnail resolution.

Why a lookup is needed at all: the CDN filename carries the gif id in its
original casing (``WealthyDramaticIndianjackal-mobile.jpg``) while the watch
URLs people post carry it lowercased. The word boundaries cannot be recovered
from ``wealthydramaticindianjackal`` without asking, and the lowercase filename
answers 403. That is why ``discover_post_thumbnail`` has no RedGIFs branch: it
is offline by contract, and offline cannot produce this value.

Why this lives outside ``message_processor.py``: the 2026-08-07 H-5 finding
removed outbound requests from the message path because that code fetched
whatever URL a post contained — redirects were not revalidated, the public-IP
check was bypassed, the response size was unbounded, and the advertised timeout
did not bite. None of those apply here: the only host contacted is a module
constant, the only attacker-controlled input is an id matched against
``[A-Za-z0-9]``, redirects are refused, and the body is read under a byte cap.
The message path nevertheless stays offline and deterministic, so the guards
pinning that (``indexer_hardening.no_remote_media`` and
``.message_processor_no_http``) remain meaningful rather than merely satisfied.

The allowlist that matters here is on the *response*, not the request. The
request host is a constant, so it needs no list; the thumbnail URL comes back
from a third party and is stored and later rendered as an image source, so it
is what has to be constrained to RedGIFs before it is written.
"""

import json
import logging
import re
import time
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

# The only host this module ever contacts. Not derived from any input.
API_ORIGIN = "https://api.redgifs.com"

# The temporary token is bound to both the calling IP and the exact User-Agent
# that requested it; a mismatch answers 401. One constant for both calls.
USER_AGENT = "mirage-indexer/1.0"

# Tokens are issued with a 24h expiry. Refresh well inside it rather than
# tracking the JWT claim, and refresh on 401 regardless.
_TOKEN_TTL = 12 * 3600

_TIMEOUT = 5
_MAX_RESPONSE_BYTES = 256 * 1024

# The gif is not coming back: never indexed, deleted, or withdrawn. Distinct
# from a transport failure, because retrying these forever would let a handful
# of dead ids occupy every backfill pass and starve the live ones.
_GONE_STATUSES = frozenset({404, 410, 451})

# Gif ids are alphanumeric — word-joined slugs or, more recently, digit strings.
_GIF_ID_RE = re.compile(r"^[A-Za-z0-9]{1,64}$")

# Paths that carry an id. "/ifr/" is the embed form, "/watch/" the share form.
_ID_PATH_PREFIXES = ("watch", "ifr")

# Parentheses are excluded because post content is markdown, so the common
# shape is [title](url) and a greedy match swallows the closing bracket.
_REDGIFS_URL_RE = re.compile(r"https?://[^\s<>\"'()\[\]]*redgifs\.com/[^\s<>\"'()\[\]]+", re.IGNORECASE)

# Sentence punctuation that ends up glued to a bare URL.
_TRAILING_PUNCT = ".,;:!?'\""


class RedgifsUnavailable(RuntimeError):
    """The API could not be reached or answered unusably. Transient by assumption."""


def extract_gif_id(raw_url: str) -> str | None:
    """Return the gif id from a RedGIFs URL, or None if it carries none."""
    try:
        parsed = urlparse(raw_url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if host != "redgifs.com" and not host.endswith(".redgifs.com"):
        return None
    parts = [p for p in (parsed.path or "").split("/") if p]
    if len(parts) < 2 or parts[0].lower() not in _ID_PATH_PREFIXES:
        return None
    candidate = parts[1]
    return candidate if _GIF_ID_RE.match(candidate) else None


def find_gif_id(media: list | None, content: str | None) -> str | None:
    """Find the gif id a root post points at, media first, then content.

    Mirrors the precedence the offline derivation uses, so a post resolves from
    the same source it would have if the value were derivable without a lookup.
    """
    if media:
        first = media[0]
        if isinstance(first, str):
            found = extract_gif_id(first)
            if found:
                return found
    for match in _REDGIFS_URL_RE.finditer(content or ""):
        found = extract_gif_id(match.group(0).rstrip(_TRAILING_PUNCT))
        if found:
            return found
    return None


def _is_redgifs_media_url(raw: str) -> bool:
    """A URL is storable only if it is https and served by RedGIFs itself."""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    return host == "redgifs.com" or host.endswith(".redgifs.com")


class RedgifsResolver:
    """Resolves gif ids to thumbnail URLs, holding the temporary token."""

    def __init__(self):
        self._token: str | None = None
        self._token_at: float = 0.0

    def _headers(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT}

    def _fetch_token(self) -> str:
        try:
            resp = requests.get(
                f"{API_ORIGIN}/v2/auth/temporary",
                headers={"User-Agent": USER_AGENT},
                timeout=_TIMEOUT,
                allow_redirects=False,
            )
        except requests.RequestException as e:
            raise RedgifsUnavailable(f"token request failed: {e}") from e
        if resp.status_code != 200:
            raise RedgifsUnavailable(f"token request returned {resp.status_code}")
        try:
            token = resp.json().get("token")
        except ValueError as e:
            raise RedgifsUnavailable(f"token response was not JSON: {e}") from e
        if not token or not isinstance(token, str):
            raise RedgifsUnavailable("token response carried no token")
        self._token = token
        self._token_at = time.time()
        return token

    def _token_now(self) -> str:
        if self._token and (time.time() - self._token_at) < _TOKEN_TTL:
            return self._token
        return self._fetch_token()

    def _get_gif(self, gif_id: str, token: str) -> requests.Response:
        try:
            return requests.get(
                f"{API_ORIGIN}/v2/gifs/{gif_id}",
                headers=self._headers(token),
                timeout=_TIMEOUT,
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as e:
            raise RedgifsUnavailable(f"gif request failed: {e}") from e

    def resolve_thumbnail(self, gif_id: str) -> str | None:
        """Return the thumbnail URL, or None if the gif is gone for good.

        Raises RedgifsUnavailable when the answer is unknown rather than
        negative, so the caller can back off instead of recording a miss.
        """
        if not _GIF_ID_RE.match(gif_id or ""):
            raise ValueError(f"refusing to request a non-id: {gif_id!r}")

        resp = self._get_gif(gif_id, self._token_now())
        if resp.status_code == 401:
            # Expired, or issued to an address this host no longer uses.
            resp.close()
            resp = self._get_gif(gif_id, self._fetch_token())
        if resp.status_code in _GONE_STATUSES:
            resp.close()
            return None
        if resp.status_code != 200:
            resp.close()
            raise RedgifsUnavailable(f"gif request returned {resp.status_code}")

        try:
            body = resp.raw.read(_MAX_RESPONSE_BYTES + 1, decode_content=True)
        except Exception as e:
            raise RedgifsUnavailable(f"reading gif response failed: {e}") from e
        finally:
            resp.close()
        if len(body) > _MAX_RESPONSE_BYTES:
            raise RedgifsUnavailable("gif response exceeded the size cap")

        try:
            payload = json.loads(body)
        except ValueError as e:
            raise RedgifsUnavailable(f"gif response was not JSON: {e}") from e

        urls = (payload.get("gif") or {}).get("urls") or {}
        # "thumbnail" is the small still; "poster" is the full-size one. Either
        # is a valid card image, so take the cheaper and fall through in order.
        for key in ("thumbnail", "poster"):
            candidate = urls.get(key)
            if isinstance(candidate, str) and _is_redgifs_media_url(candidate):
                return candidate
        logger.warning("[redgifs] no usable thumbnail URL for %s (keys=%s)", gif_id, sorted(urls))
        return None
