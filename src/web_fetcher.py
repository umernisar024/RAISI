"""
web_fetcher.py — Fetches web pages and saves them as .txt files in data/raw/.

Usage:
    Add URLs (one per line) to data/urls.txt, then run ingestion as normal.
    Already-fetched pages are skipped unless --refresh is passed.
"""

import ipaddress
import os
import re
import hashlib
import socket
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from html.parser import HTMLParser
from rich.console import Console
from src.storage_adapter import s3_upload_file

console = Console()

FETCH_DIR = Path("./data/raw/fetched")
HEADERS = {"User-Agent": "SIAgent/1.0 (RAG knowledge base builder)"}

# ── SSRF protection ───────────────────────────────────────────────────────────
# Block requests to private/internal/cloud-metadata IP ranges.
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),        # RFC1918 private
    ipaddress.ip_network("172.16.0.0/12"),      # RFC1918 private
    ipaddress.ip_network("192.168.0.0/16"),     # RFC1918 private
    ipaddress.ip_network("127.0.0.0/8"),        # loopback
    ipaddress.ip_network("169.254.0.0/16"),     # link-local / AWS metadata
    ipaddress.ip_network("::1/128"),            # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),           # IPv6 unique local
]


def _is_safe_url(url: str) -> tuple[bool, str]:
    """
    Return (True, "") if the URL is safe to fetch.
    Return (False, reason) if it should be blocked.

    Checks:
    - Scheme must be http or https
    - Host must not resolve to a private/internal IP (SSRF protection)
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Could not parse URL."

    if parsed.scheme not in ("http", "https"):
        return False, f"Scheme '{parsed.scheme}' not allowed — only http/https."

    host = parsed.hostname
    if not host:
        return False, "No hostname in URL."

    # Resolve hostname to IP and check against blocked ranges
    try:
        ip_str = socket.gethostbyname(host)
        ip = ipaddress.ip_address(ip_str)
        for network in _BLOCKED_NETWORKS:
            if ip in network:
                return False, f"Host resolves to a private/internal address ({ip}) — blocked for security."
    except socket.gaierror:
        return False, f"Could not resolve hostname '{host}'."
    except ValueError:
        return False, "Invalid IP address resolved."

    return True, ""


class _TextExtractor(HTMLParser):
    """Minimal HTML parser that strips tags and extracts readable text."""

    SKIP_TAGS = {"script", "style", "nav", "footer", "header", "noscript", "meta"}

    def __init__(self):
        super().__init__()
        self._skip = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag.lower() in self.SKIP_TAGS:
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data):
        if self._skip == 0:
            text = data.strip()
            if text:
                self.chunks.append(text)

    def get_text(self) -> str:
        raw = "\n".join(self.chunks)
        # Collapse runs of blank lines to a single blank line
        return re.sub(r"\n{3,}", "\n\n", raw).strip()


def _url_to_filename(url: str) -> str:
    """Convert a URL to a safe, readable filename."""
    # Strip scheme and sanitise
    name = re.sub(r"^https?://", "", url)
    name = re.sub(r"[^\w\-.]", "_", name)
    name = name.strip("_")[:80]
    # Append a short hash to avoid collisions between similar URLs
    short_hash = hashlib.md5(url.encode()).hexdigest()[:6]
    return f"{name}_{short_hash}.txt"


def fetch_url(url: str, output_dir: Path = FETCH_DIR, refresh: bool = False) -> Path | None:
    """
    Fetch a single URL and save its text content to output_dir.

    Returns the saved Path on success, None on failure.
    Skips already-fetched files unless refresh=True.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / _url_to_filename(url)

    if out_path.exists() and not refresh:
        console.print(f"  [dim]↩ Already fetched, skipping: {url}[/dim]")
        return out_path

    # SSRF check — block internal/private destinations
    safe, reason = _is_safe_url(url)
    if not safe:
        console.print(f"  [red]✗ Blocked ({reason}): {url}[/red]")
        return None

    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=15) as resp:
            raw_html = resp.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        console.print(f"  [red]✗ HTTP {e.code}: {url}[/red]")
        return None
    except URLError as e:
        console.print(f"  [red]✗ Failed to reach {url}: {e.reason}[/red]")
        return None
    except Exception as e:
        console.print(f"  [red]✗ Unexpected error fetching {url}: {e}[/red]")
        return None

    parser = _TextExtractor()
    parser.feed(raw_html)
    text = parser.get_text()

    if not text:
        console.print(f"  [yellow]⚠ No text extracted from {url}[/yellow]")
        return None

    # Prepend source URL so it appears in citations
    content = f"Source: {url}\n\n{text}"
    out_path.write_text(content, encoding="utf-8")
    console.print(f"  [green]✓ Fetched[/green] [dim]{url}[/dim] → {out_path.name}")

    # Back up fetched page to S3 (no-op in local mode)
    s3_upload_file(out_path, f"fetched/{out_path.name}")

    return out_path


def fetch_url_list(urls_file: str = "./data/urls.txt", refresh: bool = False) -> list[Path]:
    """
    Read a URLs file (one URL per line, # for comments) and fetch each page.

    Returns list of saved file paths ready for ingestion.
    """
    urls_path = Path(urls_file)
    if not urls_path.exists():
        return []

    lines = urls_path.read_text(encoding="utf-8").splitlines()
    urls = [
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]

    if not urls:
        return []

    console.print(f"\n[bold]Fetching {len(urls)} URL(s)...[/bold]")
    saved = []
    for url in urls:
        path = fetch_url(url, refresh=refresh)
        if path:
            saved.append(path)

    return saved
