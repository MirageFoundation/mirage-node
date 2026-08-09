"""Validation for the fleet endpoints this node will talk to.

Stats fan-out sends a signed admin proof to every server discovered from chain
state, and validator monikers are attacker-influenced text. A moniker that
already carried a scheme used to be accepted verbatim, so `http://127.0.0.1` or
a cloud metadata address became an outbound request from inside the container.

Everything a moniker or peer address turns into now goes through
`validate_fleet_endpoint`, and the request itself is sent to an address that was
checked, not to whatever DNS answers at connect time.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from typing import Optional, Tuple
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

_LABEL_RE = re.compile(r"[A-Za-z0-9-]+")


@dataclass(frozen=True)
class FleetEndpoint:
    """A destination that passed validation, with the addresses it resolved to."""

    url: str
    scheme: str
    hostname: str
    port: Optional[int]
    ips: Tuple[str, ...]

    @property
    def host_header(self) -> str:
        host = f"[{self.hostname}]" if ":" in self.hostname else self.hostname
        return f"{host}:{self.port}" if self.port else host


class _PinnedHostAdapter(HTTPAdapter):
    """Keep TLS SNI and certificate validation on the original hostname.

    The request is addressed to a validated IP, so without this the handshake
    would present and verify the wrong name.
    """

    def __init__(self, hostname: str):
        self._hostname = hostname
        super().__init__()

    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        kwargs["server_hostname"] = self._hostname
        kwargs["assert_hostname"] = self._hostname
        super().init_poolmanager(connections, maxsize, block, **kwargs)


def _is_valid_hostname(host: str) -> bool:
    if host.count(".") < 1:
        return False
    for label in host.split("."):
        if not label or len(label) > 63 or label[0] == "-" or label[-1] == "-":
            return False
        if not _LABEL_RE.fullmatch(label):
            return False
    return True


def _resolve_global_ips(hostname: str, port: int) -> Optional[Tuple[str, ...]]:
    """Every address the hostname resolves to, or None if any is not global.

    A single private answer disqualifies the host: a name that resolves to both
    a public and an internal address is the classic way to smuggle an internal
    request past a hostname check.
    """
    try:
        infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        logger.debug("fleet_url.resolve_failed host=%s err=%s", hostname, e)
        return None

    ips: list[str] = []
    for info in infos:
        ip = info[4][0]
        if ip in ips:
            continue
        try:
            parsed = ipaddress.ip_address(ip)
        except ValueError:
            return None
        if not parsed.is_global:
            logger.warning("fleet_url.rejected_non_global host=%s ip=%s", hostname, ip)
            return None
        ips.append(ip)

    return tuple(ips) or None


def validate_fleet_endpoint(raw: str, allow_ip_literal: bool = False) -> Optional[FleetEndpoint]:
    """Validate a moniker or peer address into a destination, or None to skip it.

    Bare hostnames are treated as https. IP literals are only usable where the
    caller says so (a peer's own address); a validator moniker that is an IP is
    never a stats endpoint.
    """
    value = (raw or "").strip()
    if not value or any(ch.isspace() for ch in value):
        return None

    if not value.startswith(("http://", "https://")):
        if "/" in value:
            return None
        value = f"https://{value}"

    try:
        parts = urlsplit(value)
    except ValueError:
        return None

    if parts.scheme not in ("http", "https"):
        return None
    if parts.username or parts.password or parts.query or parts.fragment:
        return None
    if parts.path not in ("", "/"):
        return None

    try:
        hostname = parts.hostname
        port = parts.port
    except ValueError:  # malformed port
        return None
    if not hostname:
        return None
    hostname = hostname.lower()
    if port is not None and not 1 <= port <= 65535:
        return None

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None

    if literal is not None:
        if not allow_ip_literal or not literal.is_global:
            return None
        ips: Tuple[str, ...] = (hostname,)
    else:
        if not _is_valid_hostname(hostname):
            return None
        resolved = _resolve_global_ips(hostname, port or (443 if parts.scheme == "https" else 80))
        if not resolved:
            return None
        ips = resolved

    host_part = f"[{hostname}]" if literal is not None and literal.version == 6 else hostname
    netloc = f"{host_part}:{port}" if port else host_part
    return FleetEndpoint(
        url=f"{parts.scheme}://{netloc}",
        scheme=parts.scheme,
        hostname=hostname,
        port=port,
        ips=ips,
    )


def post_json(endpoint: FleetEndpoint, path: str, payload: dict, timeout: float) -> requests.Response:
    """POST to a validated endpoint at a validated address.

    The connection goes to one of the addresses that passed validation, so a
    name cannot resolve to something else between the check and the request.
    Redirects are never followed: the proof in the body must not be replayed to
    a destination this node did not validate.
    """
    ip = endpoint.ips[0]
    address = f"[{ip}]" if ":" in ip else ip
    netloc = f"{address}:{endpoint.port}" if endpoint.port else address
    url = f"{endpoint.scheme}://{netloc}/{path.lstrip('/')}"

    session = requests.Session()
    session.trust_env = False
    if endpoint.scheme == "https":
        session.mount(f"https://{netloc}", _PinnedHostAdapter(endpoint.hostname))
    logger.debug("fleet_url.post host=%s ip=%s path=%s", endpoint.hostname, ip, path)
    try:
        return session.post(
            url,
            json=payload,
            headers={"Host": endpoint.host_header},
            timeout=timeout,
            allow_redirects=False,
        )
    finally:
        session.close()
