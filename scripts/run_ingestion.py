"""
run_ingestion.py — Index documents into the knowledge base.

Supports two storage backends (set STORAGE_BACKEND in .env):
  local  — reads documents from data/raw/ on the local filesystem (default)
  s3     — downloads documents from an S3 bucket before indexing

KB subfolder structure (local: data/raw/, S3: documents/):
  who_guidelines/       WHO guidelines and toolkits
  standards_docs/       HL7, FHIR, IHE, ICD and other standards
  research_papers/      Academic and research literature
  donor_guidelines/     Donor and development partner frameworks
  case_studies/         Implementation case studies and pilots
  country_profiles/     Country digital health profiles and assessments
  open_source_tools/    OpenHIE, DHIS2, OpenMRS and other platform docs
  sscp/                 SSCP project documents (priority retrieval)
  to_be_reviewed/       EXCLUDED — documents awaiting admin review

Usage:
    python scripts/run_ingestion.py                  # full ingest (local or S3)
    python scripts/run_ingestion.py --force          # re-ingest everything
    python scripts/run_ingestion.py --refresh-urls   # re-fetch all web URLs
    python scripts/run_ingestion.py --urls-only      # fetch URLs only, skip docs
    python scripts/run_ingestion.py --file data/raw/who_guidelines/x.pdf
    python scripts/run_ingestion.py --folder who_guidelines  # one folder only
"""

import sys
import os
import argparse
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

from src.ingestor import DocumentIngestor
from src.storage_adapter import StorageAdapter
from src.web_fetcher import fetch_url_list
from src.kb_submissions import (
    KB_SUBFOLDERS, STAGING_FOLDER, KB_FOLDER_LABELS, ensure_kb_dirs
)

console = Console()

# Subfolders to ingest, in order — staging folder is intentionally excluded
INGEST_ORDER = KB_SUBFOLDERS  # sscp is last so it shows as priority in output


def main():
    parser = argparse.ArgumentParser(
        description="Ingest documents into the SI Assistant knowledge base"
    )
    parser.add_argument(
        "--file",
        help="Ingest a single specific file (local only)",
    )
    parser.add_argument(
        "--folder",
        help=(
            "Ingest a single subfolder only "
            f"(choices: {', '.join(KB_SUBFOLDERS)})"
        ),
    )
    parser.add_argument(
        "--urls", default="data/urls.txt",
        help="Path to URL list file (default: data/urls.txt)",
    )
    parser.add_argument(
        "--refresh-urls", action="store_true",
        help="Re-fetch all URLs even if already cached",
    )
    parser.add_argument(
        "--urls-only", action="store_true",
        help="Only fetch and ingest URLs, skip document files",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-ingest all files even if already indexed",
    )
    args = parser.parse_args()

    backend = os.getenv("STORAGE_BACKEND", "local").lower()

    console.rule("[bold blue]SI Assistant — Ingestion Pipeline[/bold blue]")
    console.print(f"[dim]Storage backend: {backend.upper()}[/dim]\n")

    # Ensure all KB directories exist on disk
    ensure_kb_dirs()

    ingestor = DocumentIngestor()

    # ── Single file mode ──────────────────────────────────────────────────────
    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            console.print(f"[red]File not found: {args.file}[/red]")
            sys.exit(1)
        ingestor.ingest_file(file_path, force=args.force)
        console.print("\n[bold green]✓ Done.[/bold green]")
        return

    # ── Single folder mode ────────────────────────────────────────────────────
    if args.folder:
        if args.folder == STAGING_FOLDER:
            console.print(
                f"[yellow]'{STAGING_FOLDER}' is excluded from ingestion — "
                f"documents must be reviewed and moved first.[/yellow]"
            )
            sys.exit(1)
        if args.folder not in KB_SUBFOLDERS:
            console.print(
                f"[red]Unknown folder: {args.folder}. "
                f"Choose from: {', '.join(KB_SUBFOLDERS)}[/red]"
            )
            sys.exit(1)
        _ingest_one_folder(ingestor, Path("data/raw"), args.folder, args.force)
        console.print("\n[bold green]✓ Done.[/bold green]")
        return

    # ── Full ingest mode ──────────────────────────────────────────────────────

    # Step 1 — Fetch web URLs (always local, into data/raw/fetched/)
    fetch_url_list(urls_file=args.urls, refresh=args.refresh_urls)

    if args.urls_only:
        console.print("\n[bold green]✓ URL fetch complete.[/bold green]")
        return

    # Step 2 — Get the document root (local dir or S3 download)
    adapter = StorageAdapter()
    doc_root = adapter.get_document_root(local_dir="data/raw")

    if not doc_root.exists():
        console.print(
            f"[yellow]Document root not found: {doc_root}[/yellow]\n"
            f"[dim]Add documents and run again.[/dim]"
        )
    else:
        # Step 3 — Ingest root-level files (legacy / general, not in a subfolder)
        root_files = [
            f for f in doc_root.iterdir()
            if f.is_file() and f.suffix.lower() in {".pdf", ".docx", ".txt", ".md"}
        ]
        if root_files:
            console.rule("[bold]General (root level)[/bold]")
            for f in root_files:
                ingestor.ingest_file(f, force=args.force, domain="general")
            ingestor._print_summary([])

        # Step 4 — Ingest each KB subfolder in order
        for folder_name in INGEST_ORDER:
            _ingest_one_folder(ingestor, doc_root, folder_name, args.force)

        # Report that staging folder was skipped
        staging_path = doc_root / STAGING_FOLDER
        if staging_path.exists():
            staging_files = list(staging_path.iterdir())
            if staging_files:
                console.print(
                    f"\n[dim]⏭  Skipped '{STAGING_FOLDER}/' "
                    f"({len(staging_files)} file(s) awaiting review — "
                    f"use the KB Review page to approve them)[/dim]"
                )

    # Step 5 — Ingest fetched web pages (always local, in data/raw/fetched/)
    fetched_dir = Path("data/raw/fetched")
    if fetched_dir.exists() and any(fetched_dir.iterdir()):
        console.rule("[bold]Web Pages (fetched URLs)[/bold]")
        ingestor.ingest_directory(str(fetched_dir), force=args.force)

    console.print("\n[bold green]✓ Ingestion complete![/bold green]")
    console.print(
        "[dim]Run [bold]python scripts/test_search.py[/bold] "
        "to verify your knowledge base.[/dim]"
    )


def _ingest_one_folder(
    ingestor: DocumentIngestor,
    doc_root: Path,
    folder_name: str,
    force: bool,
) -> None:
    """Ingest one KB subfolder with appropriate labels and domain tagging."""
    folder_path = doc_root / folder_name
    if not folder_path.exists():
        console.print(f"[dim]  {folder_name}/ — folder not found, skipping[/dim]")
        return

    is_sscp = folder_name == "sscp"
    label = KB_FOLDER_LABELS.get(folder_name, folder_name)

    if is_sscp:
        console.rule(f"[bold cyan]{label}[/bold cyan]")
    else:
        console.rule(f"[bold]{label}[/bold]")

    ingestor.ingest_directory(str(folder_path), force=force)


if __name__ == "__main__":
    main()
