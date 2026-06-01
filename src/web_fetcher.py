"""
web_fetcher.py — Fetches web pages and saves them as .txt files in data/raw/.

Usage:
    Add URLs (one per line) to data/urls.txt, then run ingestion as normal.
    Already-fetched pages are skipped unless --refresh is passed.
"""

import http.client
import ipaddress
import os
import re
import hashlib
import socket
import ssl as _ssl_module
from pathlib import Path
from urllib.parse import urlparse
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


def _resolve_and_check(host: str) -> tuple[str | None, str]:
    """
    Resolve hostname to IP and verify it is not in a blocked private range.

    Returns (ip_str, "") on success, (None, reason) if blocked.
    Separating resolution from the safety check lets the caller reuse the
    resolved IP for the actual connection — preventing DNS rebinding attacks
    where the DNS record changes between the safety check and the request.
    """
    try:
        ip_str = socket.gethostbyname(host)
        ip = ipaddress.ip_address(ip_str)
        for network in _BLOCKED_NETWORKS:
            if ip in network:
                return None, f"Host resolves to a private/internal address ({ip}) — blocked for security."
        return ip_str, ""
    except socket.gaierror:
        return None, f"Could not resolve hostname '{host}'."
    except ValueError:
        return None, "Invalid IP address resolved."


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

    ip_str, reason = _resolve_and_check(host)
    if ip_str is None:
        return False, reason

    return True, ""


def _fetch_with_pinned_ip(url: str, resolved_ip: str, timeout: int = 15) -> str:
    """
    Fetch URL by connecting directly to resolved_ip rather than letting the OS
    re-resolve the hostname.  This closes the DNS rebinding window that exists
    when the safety check and the actual connection use separate DNS lookups.

    For HTTPS: the TLS handshake uses the original hostname for SNI and
    certificate validation, so certificate pinning still works correctly.
    For HTTP:  the TCP connection goes straight to the pre-checked IP.

    Returns the raw HTML/text body as a string.
    Raises http.client.HTTPException, OSError, or ssl.SSLError on failure.
    """
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port
    path = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
    req_headers = {**HEADERS, "Host": host}

    if parsed.scheme == "https":
        port = port or 443
        ctx = _ssl_module.create_default_context()
        conn = http.client.HTTPSConnection(
            resolved_ip, port=port, timeout=timeout, context=ctx
        )
        # Override the hostname used for SNI and cert validation so that TLS
        # checks against the original domain name, not the raw IP address.
        conn._server_hostname = host
    else:
        port = port or 80
        conn = http.client.HTTPConnection(resolved_ip, port=port, timeout=timeout)

    conn.request("GET", path, headers=req_headers)
    resp = conn.getresponse()

    if resp.status >= 400:
        raise http.client.HTTPException(f"HTTP {resp.status} {resp.reason}")

    return resp.read().decode("utf-8", errors="replace")


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

    # SSRF check — resolve hostname and verify it is not a private/internal IP.
    # We capture the resolved IP here and reuse it for the actual connection so
    # that the DNS record cannot be swapped between the safety check and the
    # request (DNS rebinding attack).
    try:
        parsed_for_check = urlparse(url)
    except Exception:
        console.print(f"  [red]✗ Could not parse URL: {url}[/red]")
        return None

    if parsed_for_check.scheme not in ("http", "https"):
        console.print(f"  [red]✗ Blocked (scheme '{parsed_for_check.scheme}' not allowed): {url}[/red]")
        return None

    if not parsed_for_check.hostname:
        console.print(f"  [red]✗ Blocked (no hostname): {url}[/red]")
        return None

    resolved_ip, reason = _resolve_and_check(parsed_for_check.hostname)
    if resolved_ip is None:
        console.print(f"  [red]✗ Blocked ({reason}): {url}[/red]")
        return None

    try:
        raw_html = _fetch_with_pinned_ip(url, resolved_ip, timeout=15)
    except http.client.HTTPException as e:
        console.print(f"  [red]✗ {e}: {url}[/red]")
        return None
    except OSError as e:
        console.print(f"  [red]✗ Failed to reach {url}: {e}[/red]")
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
