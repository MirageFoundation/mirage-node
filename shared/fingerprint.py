"""
Shared fingerprint analysis module for sock puppet and fraud detection.

Uses entropy-weighted combination scoring: individual attributes may be common,
but the combination of all attributes is unique. Rare attribute matches count
more than common ones.

Example:
    - GTX 980 WebGL: 50 users have it -> weight = log2(1000/50) = 4.3
    - 2219x1248 screen: 3 users have it -> weight = log2(1000/3) = 8.4
    - Combined score reflects that screen res match is more significant

Usage:
    from shared.fingerprint import (
        load_fingerprint_frequencies,
        load_fingerprints_from_db,
        compare_fingerprints,
        compare_all_fingerprints,
        format_match_summary,
    )
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class FingerprintData:
    """Fingerprint data for a single user."""
    user_address: str
    
    # Legacy indexed fields
    ip_hash: Optional[str] = None
    canvas_hash: Optional[str] = None
    webgl_hash: Optional[str] = None
    webgl_vendor: Optional[str] = None
    webgl_renderer: Optional[str] = None
    screen_width: Optional[int] = None
    screen_height: Optional[int] = None
    timezone: Optional[str] = None
    timezone_offset: Optional[int] = None
    platform: Optional[str] = None
    language: Optional[str] = None
    hardware_concurrency: Optional[int] = None
    device_memory: Optional[float] = None
    user_agent_hash: Optional[str] = None
    
    # Extended attributes from JSONB
    attributes: Dict[str, Any] = field(default_factory=dict)
    
    # Metadata
    first_seen: int = 0
    last_seen: int = 0
    seen_count: int = 1


@dataclass
class FingerprintFrequency:
    """Tracks how many unique users have each attribute value.
    
    Structure: {attr_name: {value_str: user_count}}
    
    Used to compute match weights: rare values = high weight.
    """
    counts: Dict[str, Dict[str, int]] = field(default_factory=dict)
    total_users: int = 0
    
    def get_count(self, attr: str, value: str) -> int:
        """Get the number of users with this attribute value."""
        return self.counts.get(attr, {}).get(value, 0)
    
    def get_weight(self, attr: str, value: str) -> float:
        """Compute match weight: log2(total_users / users_with_value).
        
        Rare values get high weights, common values get low weights.
        Returns 0 if value not found or too common.
        """
        if not value or self.total_users == 0:
            return 0.0
        count = self.get_count(attr, value)
        if count == 0:
            return 0.0
        # Weight = log2(total / count), capped at 10
        weight = math.log2(max(1, self.total_users) / max(1, count))
        return min(10.0, max(0.0, weight))


@dataclass
class FingerprintMatch:
    """Result of comparing two fingerprints."""
    user_a: str
    user_b: str
    
    # Individual attribute matches with weights
    matches: Dict[str, float] = field(default_factory=dict)  # {attr: weight}

    # Matched attribute values (as strings). Note: some fields are hashes by design.
    matched_values: Dict[str, str] = field(default_factory=dict)  # {attr: value_str}
    
    # Summary
    total_weight: float = 0.0
    max_possible_weight: float = 0.0
    score: float = 0.0  # normalized 0-1
    
    # Flags
    has_ip_match: bool = False
    has_canvas_match: bool = False
    has_device_match: bool = False  # Any high-entropy device attribute
    
    def top_matches(self, n: int = 5) -> List[Tuple[str, float]]:
        """Get the top N highest-weight matches."""
        return sorted(self.matches.items(), key=lambda x: x[1], reverse=True)[:n]


def _flatten_attributes(fp: FingerprintData) -> Dict[str, str]:
    """Flatten fingerprint data into {attr_name: value_str} for comparison."""
    result = {}
    
    # Legacy fields
    if fp.ip_hash:
        result["ip_hash"] = fp.ip_hash
    if fp.canvas_hash:
        result["canvas_hash"] = fp.canvas_hash
    if fp.webgl_hash:
        result["webgl_hash"] = fp.webgl_hash
    if fp.webgl_vendor:
        result["webgl_vendor"] = fp.webgl_vendor
    if fp.webgl_renderer:
        result["webgl_renderer"] = fp.webgl_renderer
    if fp.screen_width and fp.screen_height:
        result["screen_res"] = f"{fp.screen_width}x{fp.screen_height}"
    if fp.timezone:
        result["timezone"] = fp.timezone
    if fp.timezone_offset is not None:
        result["timezone_offset"] = str(fp.timezone_offset)
    if fp.platform:
        result["platform"] = fp.platform
    if fp.language:
        result["language"] = fp.language
    if fp.hardware_concurrency:
        result["hardware_concurrency"] = str(fp.hardware_concurrency)
    if fp.device_memory:
        result["device_memory"] = str(fp.device_memory)
    if fp.user_agent_hash:
        result["user_agent_hash"] = fp.user_agent_hash
    
    # Extended attributes from JSONB
    attrs = fp.attributes
    if not attrs:
        return result
    
    # Screen (extended)
    screen = attrs.get("screen", {})
    if screen:
        if screen.get("availWidth") and screen.get("availHeight"):
            result["screen_avail"] = f"{screen['availWidth']}x{screen['availHeight']}"
        if screen.get("colorDepth"):
            result["color_depth"] = str(screen["colorDepth"])
        if screen.get("orientation"):
            result["orientation"] = screen["orientation"]
    
    # Window
    window = attrs.get("window", {})
    if window:
        if window.get("innerWidth") and window.get("innerHeight"):
            result["window_inner"] = f"{window['innerWidth']}x{window['innerHeight']}"
        if window.get("outerWidth") and window.get("outerHeight"):
            result["window_outer"] = f"{window['outerWidth']}x{window['outerHeight']}"
        if window.get("devicePixelRatio"):
            result["pixel_ratio"] = str(window["devicePixelRatio"])
    
    # Navigator (extended)
    nav = attrs.get("navigator", {})
    if nav:
        if nav.get("vendor"):
            result["vendor"] = nav["vendor"]
        if nav.get("product"):
            result["product"] = nav["product"]
        if nav.get("productSub"):
            result["product_sub"] = nav["productSub"]
        if nav.get("buildID"):
            result["build_id"] = nav["buildID"]
        if nav.get("doNotTrack"):
            result["dnt"] = nav["doNotTrack"]
        if nav.get("maxTouchPoints"):
            result["max_touch_points"] = str(nav["maxTouchPoints"])
    
    # Plugins
    plugins = attrs.get("plugins", {})
    if plugins:
        if plugins.get("hash"):
            result["plugins_hash"] = plugins["hash"]
        if plugins.get("count") is not None:
            result["plugins_count"] = str(plugins["count"])
    
    # WebGL (extended)
    webgl = attrs.get("webgl", {})
    if webgl:
        if webgl.get("extensionsHash"):
            result["webgl_extensions_hash"] = webgl["extensionsHash"]
        if webgl.get("paramsHash"):
            result["webgl_params_hash"] = webgl["paramsHash"]
        if webgl.get("extensionsCount") is not None:
            result["webgl_extensions_count"] = str(webgl["extensionsCount"])
    
    # Audio
    audio = attrs.get("audio", {})
    if audio:
        if audio.get("sampleRate"):
            result["audio_sample_rate"] = str(audio["sampleRate"])
        if audio.get("codecsHash"):
            result["audio_codecs_hash"] = audio["codecsHash"]
        dest = audio.get("destination", {})
        if dest and dest.get("maxChannelCount"):
            result["audio_max_channels"] = str(dest["maxChannelCount"])
    
    # Video
    video = attrs.get("video", {})
    if video and video.get("codecsHash"):
        result["video_codecs_hash"] = video["codecsHash"]
    
    # Media devices
    media = attrs.get("mediaDevices", {})
    if media:
        devices_str = f"{media.get('audioInputs', 0)}a{media.get('videoInputs', 0)}v{media.get('audioOutputs', 0)}o"
        result["media_devices"] = devices_str
    
    # Storage
    storage = attrs.get("storage", {})
    if storage:
        storage_str = ""
        if storage.get("localStorage"):
            storage_str += "L"
        if storage.get("sessionStorage"):
            storage_str += "S"
        if storage.get("indexedDB"):
            storage_str += "I"
        if storage.get("cookies"):
            storage_str += "C"
        if storage_str:
            result["storage_caps"] = storage_str
    
    # Permissions
    perms = attrs.get("permissions", {})
    if perms:
        perm_str = "|".join(f"{k}:{v}" for k, v in sorted(perms.items()))
        if perm_str:
            result["permissions"] = perm_str
    
    # Touch
    touch = attrs.get("touch", {})
    if touch:
        touch_str = ""
        if touch.get("ontouchstart"):
            touch_str += "T"
        if touch.get("touchEvent"):
            touch_str += "E"
        touch_str += str(touch.get("maxTouchPoints", 0))
        result["touch_caps"] = touch_str
    
    # Intl
    intl = attrs.get("intl", {})
    if intl:
        if intl.get("locale"):
            result["intl_locale"] = intl["locale"]
        if intl.get("calendar"):
            result["intl_calendar"] = intl["calendar"]
    
    # Math fingerprint
    if attrs.get("mathHash"):
        result["math_hash"] = attrs["mathHash"]
    
    # Error stack format
    if attrs.get("errorStackFormat"):
        result["error_stack_format"] = attrs["errorStackFormat"]
    
    # HTTP headers (captured server-side)
    headers = attrs.get("httpHeaders", {})
    if headers:
        if headers.get("acceptLanguage"):
            result["http_accept_language"] = headers["acceptLanguage"]
        if headers.get("acceptEncoding"):
            result["http_accept_encoding"] = headers["acceptEncoding"]
        if headers.get("dnt"):
            result["http_dnt"] = headers["dnt"]
        if headers.get("secChUa"):
            result["http_sec_ch_ua"] = headers["secChUa"]
    
    # Connection
    conn = attrs.get("connection", {})
    if conn:
        if conn.get("effectiveType"):
            result["connection_type"] = conn["effectiveType"]
    
    return result


def load_fingerprints_from_db(cur, addresses: Optional[Set[str]] = None) -> Dict[str, List[FingerprintData]]:
    """Load fingerprints from database, optionally filtered by addresses.
    
    Returns {user_address: [FingerprintData, ...]}
    """
    if addresses:
        addr_list = [a.lower() for a in addresses]
        cur.execute(
            """
            SELECT user_address, ip_hash, canvas_hash, webgl_hash, webgl_vendor, webgl_renderer,
                   screen_width, screen_height, timezone, timezone_offset, platform, language,
                   hardware_concurrency, device_memory, user_agent_hash, attributes,
                   first_seen, last_seen, seen_count
            FROM user_fingerprints
            WHERE LOWER(user_address) = ANY(%s)
            ORDER BY user_address, last_seen DESC
            """,
            (addr_list,),
        )
    else:
        cur.execute(
            """
            SELECT user_address, ip_hash, canvas_hash, webgl_hash, webgl_vendor, webgl_renderer,
                   screen_width, screen_height, timezone, timezone_offset, platform, language,
                   hardware_concurrency, device_memory, user_agent_hash, attributes,
                   first_seen, last_seen, seen_count
            FROM user_fingerprints
            ORDER BY user_address, last_seen DESC
            """
        )
    
    result: Dict[str, List[FingerprintData]] = {}
    for row in cur.fetchall():
        addr = row[0].lower() if row[0] else ""
        if not addr:
            continue
        
        # Parse JSONB attributes
        attrs_raw = row[15]
        if isinstance(attrs_raw, str):
            try:
                attrs = json.loads(attrs_raw)
            except Exception:
                attrs = {}
        elif isinstance(attrs_raw, dict):
            attrs = attrs_raw
        else:
            attrs = {}
        
        fp = FingerprintData(
            user_address=addr,
            ip_hash=row[1],
            canvas_hash=row[2],
            webgl_hash=row[3],
            webgl_vendor=row[4],
            webgl_renderer=row[5],
            screen_width=row[6],
            screen_height=row[7],
            timezone=row[8],
            timezone_offset=row[9],
            platform=row[10],
            language=row[11],
            hardware_concurrency=row[12],
            device_memory=row[13],
            user_agent_hash=row[14],
            attributes=attrs,
            first_seen=row[16] or 0,
            last_seen=row[17] or 0,
            seen_count=row[18] or 1,
        )
        
        if addr not in result:
            result[addr] = []
        result[addr].append(fp)
    
    return result


def load_fingerprint_frequencies(cur) -> FingerprintFrequency:
    """Load fingerprint frequencies by counting unique users per attribute value.
    
    This is O(users * attributes) but only runs once per analysis session.
    """
    freq = FingerprintFrequency()
    
    # Load all fingerprints
    cur.execute(
        """
        SELECT user_address, ip_hash, canvas_hash, webgl_hash, webgl_vendor, webgl_renderer,
               screen_width, screen_height, timezone, timezone_offset, platform, language,
               hardware_concurrency, device_memory, user_agent_hash, attributes
        FROM user_fingerprints
        """
    )
    
    # Track unique users
    seen_users: Set[str] = set()
    # Track which users have which attribute values: {attr: {value: set(users)}}
    attr_users: Dict[str, Dict[str, Set[str]]] = {}
    
    for row in cur.fetchall():
        addr = row[0].lower() if row[0] else ""
        if not addr:
            continue
        
        seen_users.add(addr)
        
        # Parse JSONB attributes
        attrs_raw = row[15]
        if isinstance(attrs_raw, str):
            try:
                attrs = json.loads(attrs_raw)
            except Exception:
                attrs = {}
        elif isinstance(attrs_raw, dict):
            attrs = attrs_raw
        else:
            attrs = {}
        
        # Create temp fingerprint for flattening
        fp = FingerprintData(
            user_address=addr,
            ip_hash=row[1],
            canvas_hash=row[2],
            webgl_hash=row[3],
            webgl_vendor=row[4],
            webgl_renderer=row[5],
            screen_width=row[6],
            screen_height=row[7],
            timezone=row[8],
            timezone_offset=row[9],
            platform=row[10],
            language=row[11],
            hardware_concurrency=row[12],
            device_memory=row[13],
            user_agent_hash=row[14],
            attributes=attrs,
        )
        
        # Flatten and count
        flat = _flatten_attributes(fp)
        for attr_name, value in flat.items():
            if attr_name not in attr_users:
                attr_users[attr_name] = {}
            if value not in attr_users[attr_name]:
                attr_users[attr_name][value] = set()
            attr_users[attr_name][value].add(addr)
    
    # Convert to counts
    freq.total_users = len(seen_users)
    for attr_name, value_users in attr_users.items():
        freq.counts[attr_name] = {value: len(users) for value, users in value_users.items()}
    
    return freq


def compare_fingerprints(
    fp_a: FingerprintData,
    fp_b: FingerprintData,
    freq: FingerprintFrequency,
) -> FingerprintMatch:
    """Compare two fingerprints using entropy-weighted scoring.
    
    Each matching attribute contributes weight based on how rare the value is.
    Returns a FingerprintMatch with detailed breakdown.
    """
    match = FingerprintMatch(user_a=fp_a.user_address, user_b=fp_b.user_address)
    
    flat_a = _flatten_attributes(fp_a)
    flat_b = _flatten_attributes(fp_b)
    
    # Find matching attributes and compute weights
    all_attrs = set(flat_a.keys()) | set(flat_b.keys())
    total_weight = 0.0
    max_weight = 0.0
    
    for attr in all_attrs:
        val_a = flat_a.get(attr)
        val_b = flat_b.get(attr)
        
        if val_a and val_b:
            # Both have this attribute - compute weight
            weight = freq.get_weight(attr, val_a)
            max_weight += weight
            
            if val_a == val_b:
                # Match!
                match.matches[attr] = weight
                match.matched_values[attr] = val_a
                total_weight += weight
                
                # Set flags for key matches
                if attr == "ip_hash":
                    match.has_ip_match = True
                elif attr == "canvas_hash":
                    match.has_canvas_match = True
                elif weight >= 5.0:  # High-entropy match
                    match.has_device_match = True
    
    match.total_weight = total_weight
    match.max_possible_weight = max_weight
    
    # Normalize to 0-1 score
    if max_weight > 0:
        match.score = min(1.0, total_weight / max_weight)
    else:
        match.score = 0.0
    
    return match


def compare_all_fingerprints(
    fps_a: List[FingerprintData],
    fps_b: List[FingerprintData],
    freq: FingerprintFrequency,
) -> FingerprintMatch:
    """Compare all fingerprints from two users, return best match.
    
    Users may have multiple fingerprint records (different devices/sessions).
    We compare each pair and return the highest-scoring match.
    """
    if not fps_a or not fps_b:
        return FingerprintMatch(
            user_a=fps_a[0].user_address if fps_a else "",
            user_b=fps_b[0].user_address if fps_b else "",
        )
    
    best_match: Optional[FingerprintMatch] = None
    
    for fp_a in fps_a:
        for fp_b in fps_b:
            m = compare_fingerprints(fp_a, fp_b, freq)
            if best_match is None or m.score > best_match.score:
                best_match = m
    
    return best_match or FingerprintMatch(
        user_a=fps_a[0].user_address,
        user_b=fps_b[0].user_address,
    )


def format_match_summary(match: FingerprintMatch, max_attrs: int = 5) -> str:
    """Format a fingerprint match as a readable string.
    
    Example: "78% (screen_res: 8.4, canvas: 7.2, webgl: 4.3)"
    """
    if match.score < 0.01:
        return "0%"
    
    top = match.top_matches(max_attrs)
    if not top:
        return f"{match.score:.0%}"
    
    parts = ", ".join(f"{attr}: {weight:.1f}" for attr, weight in top)
    return f"{match.score:.0%} ({parts})"


def format_match_table(match: FingerprintMatch) -> List[str]:
    """Format a fingerprint match as a markdown table.
    
    Returns lines for a markdown table showing all matching attributes.
    """
    def _format_value(attr: str, value: str) -> str:
        if not value:
            return "-"
        # Redact hash-like values and other sensitive-ish fields by showing only a prefix.
        hash_like = (
            attr.endswith("_hash")
            or attr in {"ip_hash", "canvas_hash"}
        )
        if hash_like:
            return f"`{value[:12]}...`"
        # Keep tables readable
        if len(value) > 80:
            return f"`{value[:80]}...`"
        return f"`{value}`"

    lines = []
    lines.append("| Attribute | Value | Weight | Rarity |")
    lines.append("|-----------|-------|--------|--------|")
    
    for attr, weight in match.top_matches(20):
        value_str = _format_value(attr, match.matched_values.get(attr, ""))
        if weight >= 6.0:
            rarity = "RARE"
        elif weight >= 4.0:
            rarity = "uncommon"
        elif weight >= 2.0:
            rarity = "common"
        else:
            rarity = "very common"
        lines.append(f"| {attr} | {value_str} | {weight:.1f} | {rarity} |")
    
    lines.append("")
    lines.append(f"**Total Score: {match.score:.0%}** (weight: {match.total_weight:.1f} / {match.max_possible_weight:.1f})")
    
    return lines

