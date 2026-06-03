"""
ingestor.py — Main document ingestion pipeline.

Loads documents from data/raw/, extracts text, chunks, embeds, and stores.

Supported file types:
  .pdf    — PDF documents (WHO guidelines, FHIR specs, reports)
  .docx   — Word documents
  .txt    — Plain text files
  .md     — Markdown files
"""

import os
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

import pypdf
from docx import Document as DocxDocument

from src.chunker import DocumentChunker, Chunk
from src.embedder import Embedder
from src.store import VectorStore
from src.document_registry import register as registry_register, extract_pdf_metadata

console = Console()


class DocumentIngestor:
    """
    Orchestrates the full ingestion pipeline:
    Load file → Extract text → Chunk → Embed → Store
    """

    def __init__(
        self,
        chunk_size: int = None,
        chunk_overlap: int = None,
        db_path: str = None,
        collection_name: str = None,
        embedding_model: str = None,
    ):
        chunk_size = chunk_size or int(os.getenv("CHUNK_SIZE", 512))
        chunk_overlap = chunk_overlap or int(os.getenv("CHUNK_OVERLAP", 64))

        self.chunker = DocumentChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        self.embedder = Embedder(model_name=embedding_model)
        self.store = VectorStore(db_path=db_path, collection_name=collection_name)

    # ── File loading ──────────────────────────────────────────────────────────

    def load_pdf(self, path: Path) -> list[tuple[str, int]]:
        """
        Extract text from a PDF, page by page.
        Returns list of (page_text, page_number) tuples.
        """
        pages = []
        try:
            reader = pypdf.PdfReader(str(path))
            for page_num, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                if text.strip():
                    pages.append((text, page_num))
        except Exception as e:
            console.print(f"[red]  Error reading PDF {path.name}: {e}[/red]")
        return pages

    def load_docx(self, path: Path) -> list[tuple[str, None]]:
        """Extract text from a Word document."""
        try:
            doc = DocxDocument(str(path))
            full_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            return [(full_text, None)]
        except Exception as e:
            console.print(f"[red]  Error reading DOCX {path.name}: {e}[/red]")
            return []

    def load_text(self, path: Path) -> list[tuple[str, None]]:
        """Load plain text or markdown file."""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            return [(text, None)]
        except Exception as e:
            console.print(f"[red]  Error reading {path.name}: {e}[/red]")
            return []

    def load_file(self, path: Path) -> list[tuple[str, Optional[int]]]:
        """Dispatch to the right loader based on file extension."""
        ext = path.suffix.lower()
        if ext == ".pdf":
            return self.load_pdf(path)
        elif ext == ".docx":
            return self.load_docx(path)
        elif ext in (".txt", ".md"):
            return self.load_text(path)
        else:
            console.print(f"[yellow]  Skipping unsupported file type: {path.name}[/yellow]")
            return []

    # ── Pipeline ──────────────────────────────────────────────────────────────

    def ingest_file(self, path: Path, force: bool = False, sscp: bool = False, domain: str = None) -> dict:
        """
        Full pipeline for a single file.
        Skips files already indexed unless force=True.

        sscp=True tags all chunks from this file as SSCP priority content.
        This is set automatically when the file lives in data/raw/sscp/.

        Returns a summary dict with stats.
        """
        # Auto-detect SSCP based on parent folder name
        is_sscp = sscp or path.parent.name.lower() == "sscp"
        # Use explicit domain if provided, otherwise derive from subfolder name
        resolved_domain = domain or path.parent.name.lower() or "general"

        # Skip if already in the KB (saves all loading, chunking, embedding work)
        if not force and self.store.has_source(path.name):
            console.print(f"  [dim]↩ Already indexed, skipping: {path.name}[/dim]")
            return {"file": path.name, "status": "skipped", "chunks_added": 0}

        sscp_label = " [cyan][SSCP][/cyan]" if is_sscp else ""
        console.print(f"\n[bold]Processing:[/bold] {path.name}{sscp_label}")

        # 1. Load
        pages = self.load_file(path)
        if not pages:
            return {"file": path.name, "status": "failed", "chunks": 0}

        # 2. Chunk (page by page for PDFs, whole doc for others)
        all_chunks: list[Chunk] = []
        for text, page_num in pages:
            chunks = self.chunker.chunk_document(
                text=text,
                source_file=path.name,
                page_number=page_num,
                sscp=is_sscp,
                domain=resolved_domain,
            )
            all_chunks.extend(chunks)

        if not all_chunks:
            console.print(f"[yellow]  No chunks extracted[/yellow]")
            return {"file": path.name, "status": "empty", "chunks": 0}

        console.print(f"  [dim]→ {len(all_chunks)} chunks extracted[/dim]")

        # 3. Embed
        console.print(f"  [dim]→ Generating embeddings...[/dim]")
        texts = [c.text for c in all_chunks]
        embeddings = self.embedder.embed_documents(texts)

        # 4. Store
        added = self.store.add_chunks(all_chunks, embeddings)
        console.print(f"  [green]✓ {added} chunks added to knowledge base[/green]")

        # 5. Register in document registry (auto-extract PDF metadata)
        pdf_meta = extract_pdf_metadata(path) if path.suffix.lower() == ".pdf" else {}
        registry_register(
            source_file=path.name,
            title=pdf_meta.get("title", ""),
            authors=pdf_meta.get("authors", ""),
            year=pdf_meta.get("year", ""),
            domain=resolved_domain,
        )

        return {
            "file": path.name,
            "status": "ok",
            "pages": len(pages),
            "chunks_extracted": len(all_chunks),
            "chunks_added": added,
        }

    def ingest_directory(self, directory: str = "./data/raw", force: bool = False) -> list[dict]:
        """
        Ingest all supported documents in a directory.
        Skips files already in the knowledge base unless force=True.
        Returns a list of result dicts (one per file).
        """
        dir_path = Path(directory)
        if not dir_path.exists():
            console.print(f"[red]Directory not found: {directory}[/red]")
            return []

        supported = {".pdf", ".docx", ".txt", ".md"}
        files = [f for f in dir_path.iterdir() if f.suffix.lower() in supported]

        if not files:
            console.print(
                f"[yellow]No supported documents found in {directory}[/yellow]\n"
                f"[dim]Add PDFs, Word docs, or text files and run again.[/dim]"
            )
            return []

        new_files = [f for f in files if force or not self.store.has_source(f.name)]
        skipped = len(files) - len(new_files)

        if skipped:
            console.print(f"[dim]↩ {skipped} file(s) already indexed — skipping.[/dim]"
                          f" [dim](use --force to re-ingest everything)[/dim]")

        if not new_files:
            console.print("[green]✓ Knowledge base is up to date. Nothing to do.[/green]")
            return []

        is_sscp_dir = dir_path.name.lower() == "sscp"
        if is_sscp_dir:
            console.print(f"\n[bold cyan]Ingesting {len(new_files)} SSCP document(s)...[/bold cyan]")
        else:
            console.print(f"\n[bold]Ingesting {len(new_files)} new document(s)...[/bold]")

        results = []
        for file in new_files:
            result = self.ingest_file(file, force=force, sscp=is_sscp_dir)
            results.append(result)

        self._print_summary(results)
        return results

    def _print_summary(self, results: list[dict]):
        """Print a nice summary table after ingestion."""
        console.print("\n")
        table = Table(title="Ingestion Summary", show_lines=True)
        table.add_column("File", style="bold")
        table.add_column("Status")
        table.add_column("Chunks added", justify="right")

        for r in results:
            status_style = "green" if r["status"] == "ok" else "yellow"
            table.add_row(
                r["file"],
                f"[{status_style}]{r['status']}[/{status_style}]",
                str(r.get("chunks_added", 0)),
            )

        console.print(table)

        # Print KB stats
        stats = self.store.stats()
        console.print(f"\n[bold]Knowledge base total:[/bold] "
                      f"{stats['total_chunks']} chunks")
        console.print(f"[dim]By domain:[/dim] {stats['by_domain']}")
        console.print(f"[dim]By language:[/dim] {stats['by_language']}")
