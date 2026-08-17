"""Rumble video resolution.

Rumble runs two separate id namespaces and the URLs people post carry the wrong
one for embedding. ``https://rumble.com/v7b3y1w-outlaws-samuel-roth.html`` is
watch id ``v7b3y1w``, but its embed is ``https://rumble.com/embed/v78xa1o/``.
The two are unrelated, and worse, they collide: ``/embed/v7b3y1w/`` is a valid
embed belonging to a different video entirely, so deriving one from the other
does not fail loudly — it silently plays a stranger's video. Only Rumble can
map between them, via the oEmbed endpoint, which returns the correct embed and
the thumbnail in one answer.

Unlike the RedGIFs resolver, the request cannot be rebuilt from an id alone:
oEmbed matches on the full watch URL including its slug, and ``/v7b3y1w`` or
``/v7b3y1w.html`` both 404. So the posted URL does reach the wire — but only
after its host is confirmed to be Rumble and its path is matched against the
watch-page shape, and only ever as a urlencoded query parameter of a fixed
endpoint on a fixed host. Nothing user-supplied can move the request.

As with RedGIFs, this stays out of ``message_processor.py``: block projection
must remain offline and deterministic.
"""

import json
import logging
import re
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlparse

logger = logging.getLogger(__name__)

# The only endpoint this module ever contacts.
OEMBED_ENDPOINT = "https://rumble.com/api/Media/oembed.json"

# Rumble answers 403 to `requests` no matter what headers it is given, browser
# User-Agent included, and answers normally to the stdlib client — so this one
# module does not use the `requests` the rest of the indexer uses. It also 403s
# the default "Python-urllib/x.y", so the User-Agent below is load-bearing
# rather than decorative.
USER_AGENT = "mirage-indexer/1.0"

_TIMEOUT = 5
_MAX_RESPONSE_BYTES = 256 * 1024

_GONE_STATUSES = frozenset({404, 410, 451})

_WATCH_HOSTS = frozenset({"rumble.com", "www.rumble.com"})

# Watch pages are "/vXXXX-some-slug.html". The id is what the frontend reads
# today; the slug is what oEmbed needs, so both have to survive validation.
# The extension is stripped after matching rather than in the pattern: the slug
# class contains ".", so an optional suffix group would never get the chance.
_WATCH_PATH_RE = re.compile(r"^/(v[a-z0-9]+-[a-z0-9._-]{1,200})$", re.IGNORECASE)
_HTML_SUFFIX_RE = re.compile(r"\.html?$", re.IGNORECASE)

# Embed paths carry the other namespace, optionally publisher-qualified.
_EMBED_PATH_RE = re.compile(r"^/embed/((?:[a-z0-9]+\.)?v[a-z0-9]+)/?$", re.IGNORECASE)

# What may be stored as an embed id, and therefore interpolated into an iframe
# src by the clients.
_EMBED_ID_RE = re.compile(r"^(?:[a-z0-9]+\.)?v[a-z0-9]+$", re.IGNORECASE)

# Hosts Rumble serves thumbnails from. Narrow on purpose: the value is stored
# and later rendered as an image source.
_THUMB_HOSTS = frozenset({"1a-1791.com", "rumble.com", "sp.rmbl.ws"})
_THUMB_HOST_SUFFIXES = (".rmbl.ws",)

# Parentheses are excluded because post content is markdown, so the common
# shape is [title](url) and a greedy match swallows the closing bracket.
_RUMBLE_URL_RE = re.compile(r"https?://(?:www\.)?rumble\.com/[^\s<>\"'()\[\]]+", re.IGNORECASE)

# Sentence punctuation that ends up glued to a bare URL.
_TRAILING_PUNCT = ".,;:!?'\""


class RumbleUnavailable(RuntimeError):
    """oEmbed could not be reached or answered unusably. Transient by assumption."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects; returning None makes urllib raise the 3xx as an error."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def canonical_watch_url(raw_url: str) -> str | None:
    """Return the bare Rumble URL to ask oEmbed about, or None if it is not one.

    Query and fragment are dropped: they carry referral tracking that oEmbed
    does not need and that has no business being sent onward.
    """
    try:
        parsed = urlparse(raw_url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    if (parsed.hostname or "").lower() not in _WATCH_HOSTS:
        return None

    embed = _EMBED_PATH_RE.match(parsed.path or "")
    if embed:
        return f"https://rumble.com/embed/{embed.group(1)}/"
    watch = _WATCH_PATH_RE.match(parsed.path or "")
    if watch:
        return f"https://rumble.com/{_HTML_SUFFIX_RE.sub('', watch.group(1))}.html"
    return None


def find_watch_url(media: list | None, content: str | None) -> str | None:
    """Find the Rumble URL a root post points at, media first, then content."""
    if media:
        first = media[0]
        if isinstance(first, str):
            found = canonical_watch_url(first)
            if found:
                return found
    for match in _RUMBLE_URL_RE.finditer(content or ""):
        found = canonical_watch_url(match.group(0).rstrip(_TRAILING_PUNCT))
        if found:
            return found
    return None


def _is_rumble_thumbnail_url(raw: str) -> bool:
    try:
        parsed = urlparse(raw)
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    return host in _THUMB_HOSTS or host.endswith(_THUMB_HOST_SUFFIXES)


def _embed_id_from_html(html: str) -> str | None:
    """Pull the embed id out of the iframe oEmbed hands back."""
    match = re.search(r"https://rumble\.com/embed/([^/\"']+)/", html or "")
    if not match:
        return None
    candidate = match.group(1)
    return candidate if _EMBED_ID_RE.match(candidate) else None


class RumbleResolver:
    """Resolves a Rumble watch URL to its embed id and thumbnail."""

    def resolve(self, watch_url: str) -> dict | None:
        """Return {"embed_id", "thumbnail"} or None if the video is gone.

        Either value may be absent from the answer; the caller stores what it
        gets. Raises RumbleUnavailable when the answer is unknown rather than
        negative.
        """
        if canonical_watch_url(watch_url) != watch_url:
            raise ValueError(f"refusing to request a non-canonical Rumble URL: {watch_url!r}")

        request = urllib.request.Request(
            f"{OEMBED_ENDPOINT}?{urlencode({'url': watch_url})}",
            headers={"User-Agent": USER_AGENT},
        )
        try:
            with _OPENER.open(request, timeout=_TIMEOUT) as resp:
                if resp.status != 200:
                    raise RumbleUnavailable(f"oembed returned {resp.status}")
                body = resp.read(_MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as e:
            e.close()
            if e.code in _GONE_STATUSES:
                return None
            raise RumbleUnavailable(f"oembed returned {e.code}") from e
        except urllib.error.URLError as e:
            raise RumbleUnavailable(f"oembed request failed: {e.reason}") from e
        except OSError as e:
            raise RumbleUnavailable(f"oembed request failed: {e}") from e

        if len(body) > _MAX_RESPONSE_BYTES:
            raise RumbleUnavailable("oembed response exceeded the size cap")

        try:
            payload = json.loads(body)
        except ValueError as e:
            raise RumbleUnavailable(f"oembed response was not JSON: {e}") from e
        if not isinstance(payload, dict):
            raise RumbleUnavailable("oembed response was not an object")

        embed_id = _embed_id_from_html(payload.get("html") or "")
        thumbnail = payload.get("thumbnail_url")
        if not (isinstance(thumbnail, str) and _is_rumble_thumbnail_url(thumbnail)):
            thumbnail = None

        if not embed_id and not thumbnail:
            logger.warning("[rumble] oembed carried neither embed nor thumbnail for %s", watch_url)
            return None
        return {"embed_id": embed_id, "thumbnail": thumbnail}
