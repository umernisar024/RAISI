"""
test_search.py — Test semantic search over your knowledge base.

Run this after ingestion to confirm retrieval is working.

Usage:
    python scripts/test_search.py
    python scripts/test_search.py --query "how to implement FHIR in a low resource setting"
"""

import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

from src.embedder import Embedder
from src.store import VectorStore

console = Console()

# Sample queries relevant to digital health in LMICs
SAMPLE_QUERIES = [
    "What are the core components of a health information exchange?",
    "How does FHIR support interoperability in low resource settings?",
    "What is the OpenHIE architecture?",
    "DHIS2 implementation best practices for national health systems",
    "How to implement patient identity management in LMICs?",
]


def run_search(query: str, embedder: Embedder, store: VectorStore, n: int = 3):
    """Run a single search and print results."""
    console.print(f"\n[bold]Query:[/bold] {query}")

    query_embedding = embedder.embed_query(query)
    results = store.search(query_embedding, n_results=n)

    if not results:
        console.print("[yellow]  No results found. Make sure you've ingested documents first.[/yellow]")
        return

    for i, r in enumerate(results, 1):
        meta = r["metadata"]
        score = r["score"]
        text_preview = r["text"][:300] + "..." if len(r["text"]) > 300 else r["text"]

        score_color = "green" if score > 0.7 else "yellow" if score > 0.5 else "red"

        console.print(
            Panel(
                f"[dim]{text_preview}[/dim]\n\n"
                f"[bold]Source:[/bold] {meta.get('source_file', 'unknown')} "
                f"(page {meta.get('page_number', 'N/A')})  "
                f"[bold]Domain:[/bold] {meta.get('domain', 'N/A')}  "
                f"[bold]Score:[/bold] [{score_color}]{score:.3f}[/{score_color}]",
                title=f"Result {i}",
                border_style="dim",
            )
        )


def main():
    parser = argparse.ArgumentParser(description="Test search over the knowledge base")
    parser.add_argument("--query", help="Custom search query to test")
    parser.add_argument("--n", type=int, default=3, help="Number of results (default: 3)")
    args = parser.parse_args()

    console.rule("[bold blue]Digital Health KB — Search Test[/bold blue]")

    embedder = Embedder()
    store = VectorStore()

    stats = store.stats()
    console.print(f"\n[bold]Knowledge base:[/bold] {stats['total_chunks']} chunks indexed")
    console.print(f"[dim]Domains:[/dim] {stats['by_domain']}")
    console.print(f"[dim]Languages:[/dim] {stats['by_language']}")

    if stats["total_chunks"] == 0:
        console.print(
            "\n[red]Knowledge base is empty![/red]\n"
            "Run [bold]python scripts/run_ingestion.py[/bold] first."
        )
        sys.exit(1)

    if args.query:
        run_search(args.query, embedder, store, n=args.n)
    else:
        console.print("\n[dim]Running sample queries to test retrieval...[/dim]")
        for query in SAMPLE_QUERIES[:3]:  # test first 3 by default
            run_search(query, embedder, store, n=args.n)


if __name__ == "__main__":
    main()
