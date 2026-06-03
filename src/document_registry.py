"""
document_registry.py — Metadata catalog for all indexed documents.

Stored at data/document_registry.json, keyed by source_file (the filename
as stored in ChromaDB).  Populated automatically during ingestion and
enriched when documents go through the KB submission workflow.

Fields per record:
  source_file   — filename as stored in ChromaDB (e.g. "who_guidelines.pdf")
  title         — human-readable document title
  authors       — author name(s)
  organization  — publishing organisation (e.g. "WHO", "HL7", "CSIRO")
  year          — publication year string (e.g. "2021")
  url           — source URL if available
  description   — short description
  domain        — KB subfolder domain (e.g. "who_guidelines")
  category      — human-readable category label
  date_indexed  — ISO timestamp when first indexed
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REGISTRY_FILE = Path("data/document_registry.json")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load() -> dict:
    if not REGISTRY_FILE.exists():
        return {}
    try:
        return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ── Public API ────────────────────────────────────────────────────────────────

def register(
    source_file: str,
    title: str = "",
    authors: str = "",
    organization: str = "",
    year: str = "",
    url: str = "",
    description: str = "",
    domain: str = "",
    category: str = "",
    overwrite: bool = False,
) -> dict:
    """
    Register a document in the registry.

    Safe to call on re-ingest — if the record already exists and
    overwrite=False the existing record is returned unchanged.
    Returns the (possibly new) record.
    """
    data = _load()

    if source_file in data and not overwrite:
        return data[source_file]

    record = {
        "source_file": source_file,
        "title": title.strip() or source_file,
        "authors": authors.strip(),
        "organization": organization.strip(),
        "year": year.strip(),
        "url": url.strip(),
        "description": description.strip(),
        "domain": domain,
        "category": category,
        "date_indexed": datetime.now(timezone.utc).isoformat(),
    }

    data[source_file] = record
    _save(data)
    return record


def get(source_file: str) -> Optional[dict]:
    """Return registry record for a source file, or None if not registered."""
    return _load().get(source_file)


def get_all() -> list[dict]:
    """Return all registry records as a list, sorted alphabetically by title."""
    data = _load()
    return sorted(data.values(), key=lambda r: (r.get("title") or "").lower())


def update(source_file: str, **fields) -> bool:
    """
    Update one or more fields for a registered document.
    Returns True if the record was found and updated, False if not found.
    """
    data = _load()
    if source_file not in data:
        return False
    data[source_file].update(fields)
    _save(data)
    return True


def delete(source_file: str) -> bool:
    """Remove a document from the registry. Returns True if it existed."""
    data = _load()
    if source_file in data:
        del data[source_file]
        _save(data)
        return True
    return False


def format_citation(source_file: str) -> str:
    """
    Return a formatted citation string for display in chat sources.
    Falls back gracefully to the raw filename if not registered.

    Examples:
      "WHO Digital Health Guidelines (WHO, 2021)"
      "FHIR R4 Specification (HL7)"
      "national_strategy.pdf"  ← fallback
    """
    record = get(source_file)
    if not record:
        return source_file

    title = record.get("title") or source_file
    org   = record.get("organization") or record.get("authors") or ""
    year  = record.get("year") or ""

    if org and year:
        return f"{title} ({org}, {year})"
    elif org:
        return f"{title} ({org})"
    elif year:
        return f"{title} ({year})"
    else:
        return title


def extract_pdf_metadata(path) -> dict:
    """
    Extract title, author, and year from a PDF's embedded metadata.
    Returns a dict with keys: title, authors, year.
    Returns empty strings on failure — never raises.
    """
    title = authors = year = ""
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        meta = reader.metadata or {}

        title = (
            str(meta.get("/Title", "") or meta.get("title", "") or "")
            .strip()
            .strip("\x00")
        )
        authors = (
            str(meta.get("/Author", "") or meta.get("author", "") or "")
            .strip()
            .strip("\x00")
        )

        # CreationDate format: "D:20210315120000+00'00'" — extract 4-digit year
        date_str = str(meta.get("/CreationDate", "") or "")
        if date_str.startswith("D:") and len(date_str) >= 6:
            candidate = date_str[2:6]
            if candidate.isdigit():
                year = candidate
        elif len(date_str) >= 4 and date_str[:4].isdigit():
            year = date_str[:4]

    except Exception:
        pass

    return {"title": title, "authors": authors, "year": year}
