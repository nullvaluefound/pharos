"""URL canonicalization and content fingerprints for deduplication."""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Tracking parameters that should not be part of the canonical URL.
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_name", "utm_brand", "utm_social", "utm_social-type",
    "fbclid", "gclid", "mc_cid", "mc_eid", "yclid", "_hsenc", "_hsmi",
    "ref", "ref_src", "ref_url", "source",
}


def canonicalize_url(url: str) -> str:
    """Return a normalized URL suitable for deduplication."""
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    host = parts.hostname.lower() if parts.hostname else ""
    if parts.port and not (
        (scheme == "http" and parts.port == 80) or (scheme == "https" and parts.port == 443)
    ):
        host = f"{host}:{parts.port}"
    path = re.sub(r"/+", "/", parts.path or "/")
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    query_pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
                   if k.lower() not in _TRACKING_PARAMS]
    query_pairs.sort()
    query = urlencode(query_pairs, doseq=True)
    return urlunsplit((scheme, host, path, query, ""))


def url_hash(url: str) -> str:
    """Stable hex hash of the canonical URL."""
    return hashlib.sha256(canonicalize_url(url).encode("utf-8")).hexdigest()


_word_re = re.compile(r"[A-Za-z0-9']+")


def content_simhash(text: str, *, bits: int = 64) -> str:
    """Compute a 64-bit SimHash of the article body, returned as hex.

    SimHash gives near-duplicates similar bit patterns; we store the hex string
    as a quick coarse signal alongside per-token clustering done by the lantern.
    """
    if not text:
        return "0" * (bits // 4)
    vec = [0] * bits
    for token in _word_re.findall(text.lower()):
        h = int.from_bytes(hashlib.md5(token.encode("utf-8")).digest()[:8], "big")
        for i in range(bits):
            vec[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i in range(bits):
        if vec[i] > 0:
            out |= 1 << i
    return f"{out:0{bits // 4}x}"


def hamming_distance_hex(a: str, b: str) -> int:
    """Hamming distance between two equal-length hex strings."""
    return bin(int(a, 16) ^ int(b, 16)).count("1")
