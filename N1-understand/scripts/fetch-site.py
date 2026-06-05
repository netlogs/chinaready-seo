#!/usr/bin/env python3
"""
Fetch a SaaS site and extract structured signals for scenario / need analysis.

Pulls the kind of on-page evidence needed to reason about *who the product is
for*, *what scenario they are in*, and *what need it solves* — so the analyst
can derive seed keywords grounded in real page content, not guesses.

Extracts per page: title, meta description, H1-H3 headings, primary nav labels,
CTA button/link text, and a trimmed visible-text excerpt. Also pulls the
sitemap.xml URL list when available, to reveal the site's page inventory
(each URL is a content theme = a keyword cluster candidate).

Usage:
    python fetch-site.py https://example.com
    python fetch-site.py https://example.com --pages /pricing /features /transit-checker
    python fetch-site.py https://example.com --max-sitemap 50 > site.json

Output: a single JSON object on stdout. Designed to be read by the LLM, not a human.

Dependencies: pip install requests   (HTML parsing uses Python stdlib only)
"""

import argparse
import ipaddress
import json
import re
import socket
import sys
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urljoin, urlparse

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 ChinaReadyWebAna/1.0"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}

# Tags whose text content is never user-facing copy
_SKIP_TEXT_TAGS = {"script", "style", "noscript", "template", "svg"}

# Local proxies (Clash/sing-box/Surge) in fake-ip TUN mode map domains into
# this benchmarking range; the proxy forwards the real request. Allow-list it.
_FAKE_IP_RANGE = ipaddress.ip_network("198.18.0.0/15")
# Tags that commonly hold CTA / action labels
_CTA_TAGS = {"button", "a"}
_CTA_HINT = re.compile(
    r"\b(start|try|get|buy|sign\s?up|signup|download|book|check|free|demo|"
    r"subscribe|join|install|launch|create|build|upgrade|plan|pricing)\b",
    re.I,
)


class _PageParser(HTMLParser):
    """Single-pass HTML parser collecting structured page signals."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta_description = ""
        self.meta_keywords = ""
        self.og_title = ""
        self.og_description = ""
        self.headings: dict[str, list[str]] = {"h1": [], "h2": [], "h3": []}
        self.nav_labels: list[str] = []
        self.cta_labels: list[str] = []
        self.text_chunks: list[str] = []

        self._skip_depth = 0          # inside script/style/etc.
        self._nav_depth = 0           # inside <nav>
        self._cur_tag: Optional[str] = None
        self._cur_attrs: dict = {}
        self._buf: list[str] = []     # text buffer for the current capturing tag

    # -- tag lifecycle -----------------------------------------------------
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        ad = {k.lower(): (v or "") for k, v in attrs}

        if tag in _SKIP_TEXT_TAGS:
            self._skip_depth += 1
            return
        if tag == "nav":
            self._nav_depth += 1
        if tag == "meta":
            self._handle_meta(ad)
            return

        if tag == "title" or tag in self.headings or tag in _CTA_TAGS:
            self._cur_tag = tag
            self._cur_attrs = ad
            self._buf = []

    def handle_startendtag(self, tag, attrs):
        # self-closing tags (e.g. <meta .../>)
        if tag.lower() == "meta":
            self._handle_meta({k.lower(): (v or "") for k, v in attrs})

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _SKIP_TEXT_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "nav":
            self._nav_depth = max(0, self._nav_depth - 1)

        if tag == self._cur_tag:
            text = _clean(" ".join(self._buf))
            if text:
                if tag == "title":
                    if not self.title:
                        self.title = text
                elif tag in self.headings:
                    self.headings[tag].append(text)
                elif tag in _CTA_TAGS:
                    # nav links → nav_labels; action-y links/buttons → cta_labels
                    if self._nav_depth > 0 and tag == "a":
                        self.nav_labels.append(text)
                    elif tag == "button" or _CTA_HINT.search(text):
                        self.cta_labels.append(text)
            self._cur_tag = None
            self._cur_attrs = {}
            self._buf = []

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        if self._cur_tag is not None:
            self._buf.append(data)
        # always feed visible text into the body excerpt pool
        stripped = data.strip()
        if stripped:
            self.text_chunks.append(stripped)

    # -- helpers -----------------------------------------------------------
    def _handle_meta(self, ad: dict):
        name = ad.get("name", "").lower()
        prop = ad.get("property", "").lower()
        content = ad.get("content", "").strip()
        if not content:
            return
        if name == "description" and not self.meta_description:
            self.meta_description = content
        elif name == "keywords" and not self.meta_keywords:
            self.meta_keywords = content
        elif prop == "og:title" and not self.og_title:
            self.og_title = content
        elif prop == "og:description" and not self.og_description:
            self.og_description = content


def _clean(text: str) -> str:
    """Collapse whitespace; return a single trimmed line."""
    return re.sub(r"\s+", " ", text or "").strip()


def _dedup(seq: list[str], limit: int) -> list[str]:
    """Order-preserving dedup, capped at `limit` items."""
    seen: set[str] = set()
    out: list[str] = []
    for item in seq:
        key = item.lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item)
        if len(out) >= limit:
            break
    return out


def _guard_ssrf(url: str) -> Optional[str]:
    """Return an error string if the URL resolves to a private/internal IP.

    Allows the 198.18.0.0/15 benchmarking range: local proxies (Clash /
    sing-box / Surge) in fake-ip TUN mode map public domains into this range,
    and the real request is forwarded by the proxy to the genuine server.
    Modern Python classifies that range as is_private, so it must be allow-listed
    explicitly — otherwise the script is unusable behind a fake-ip proxy.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"Invalid URL scheme: {parsed.scheme}"
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(parsed.hostname or ""))
        if ip in _FAKE_IP_RANGE:
            return None  # proxy fake-ip, not real internal infra
        if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
            return f"Blocked: resolves to private/internal IP ({ip})"
    except (socket.gaierror, ValueError):
        pass  # DNS errors surface during the actual request
    return None


def fetch_page(url: str, timeout: int = 30) -> dict:
    """Fetch one page and return parsed signals (or an error)."""
    result: dict = {"url": url, "status_code": None, "error": None}

    err = _guard_ssrf(url)
    if err:
        result["error"] = err
        return result

    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        # requests defaults to ISO-8859-1 when the server omits charset; trust
        # the body's own detected encoding so em-dashes / CJK decode correctly.
        if "charset" not in resp.headers.get("Content-Type", "").lower():
            resp.encoding = resp.apparent_encoding or resp.encoding
        result["url"] = resp.url
        result["status_code"] = resp.status_code
        ctype = resp.headers.get("Content-Type", "")
        if "html" not in ctype.lower():
            result["error"] = f"Not HTML (Content-Type: {ctype})"
            return result

        parser = _PageParser()
        parser.feed(resp.text)

        body_excerpt = _clean(" ".join(parser.text_chunks))
        result.update(
            {
                "title": parser.title,
                "meta_description": parser.meta_description,
                "meta_keywords": parser.meta_keywords,
                "og_title": parser.og_title,
                "og_description": parser.og_description,
                "h1": _dedup(parser.headings["h1"], 10),
                "h2": _dedup(parser.headings["h2"], 30),
                "h3": _dedup(parser.headings["h3"], 40),
                "nav_labels": _dedup(parser.nav_labels, 40),
                "cta_labels": _dedup(parser.cta_labels, 25),
                "body_excerpt": body_excerpt[:2500],
            }
        )
    except requests.exceptions.Timeout:
        result["error"] = f"Request timed out after {timeout}s"
    except requests.exceptions.RequestException as e:
        result["error"] = f"Request failed: {e}"
    return result


def fetch_sitemap_urls(origin: str, limit: int, timeout: int = 30) -> dict:
    """Fetch sitemap.xml from the origin and return its <loc> URL list.

    Handles a sitemap index by following child sitemaps until `limit` URLs
    are collected. Returns {"sitemap_url", "urls", "error"}.
    """
    sm_url = urljoin(origin, "/sitemap.xml")
    out: dict = {"sitemap_url": sm_url, "urls": [], "error": None}
    loc_re = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.I | re.S)

    def _pull(u: str) -> list[str]:
        if _guard_ssrf(u):
            return []
        r = requests.get(u, headers=HEADERS, timeout=timeout, allow_redirects=True)
        if r.status_code != 200:
            return []
        return [_clean(m) for m in loc_re.findall(r.text)]

    try:
        locs = _pull(sm_url)
        if not locs:
            out["error"] = "sitemap.xml missing or empty"
            return out
        # Detect sitemap index (entries are themselves .xml sitemaps)
        if any(l.lower().endswith(".xml") for l in locs):
            collected: list[str] = []
            for child in locs:
                if len(collected) >= limit:
                    break
                collected.extend(_pull(child))
            locs = collected
        out["urls"] = _dedup(locs, limit)
    except requests.exceptions.RequestException as e:
        out["error"] = f"sitemap fetch failed: {e}"
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch a SaaS site and extract scenario/need signals as JSON"
    )
    parser.add_argument("url", help="Homepage URL of the SaaS site")
    parser.add_argument(
        "--pages",
        nargs="*",
        default=[],
        help="Extra paths or URLs to fetch (e.g. /pricing /features). "
        "Relative paths resolve against the homepage origin.",
    )
    parser.add_argument(
        "--max-sitemap",
        type=int,
        default=60,
        help="Max sitemap URLs to return (default 60)",
    )
    parser.add_argument("--timeout", type=int, default=30, help="Per-request timeout (s)")
    args = parser.parse_args()

    home_url = args.url if urlparse(args.url).scheme else f"https://{args.url}"
    origin = f"{urlparse(home_url).scheme}://{urlparse(home_url).netloc}"

    report: dict = {"input_url": args.url, "origin": origin, "pages": []}

    # Homepage first
    report["pages"].append(fetch_page(home_url, timeout=args.timeout))

    # Extra pages requested by the analyst
    for p in args.pages:
        full = p if urlparse(p).scheme else urljoin(origin + "/", p.lstrip("/"))
        report["pages"].append(fetch_page(full, timeout=args.timeout))

    # Page inventory from sitemap
    report["sitemap"] = fetch_sitemap_urls(origin, args.max_sitemap, timeout=args.timeout)

    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
