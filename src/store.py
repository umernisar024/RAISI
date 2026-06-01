"""
store.py — ChromaDB vector store interface.

ChromaDB is a local vector database that runs entirely on your machine.
No server setup, no cloud account — just a folder on disk.

The database is stored at: data/chroma_db/
"""

import os
import uuid
from typing import Optional
import chromadb
from chromadb.config import Settings
from rich.console import Console

from src.chunker import Chunk

console = Console()


class VectorStore:
    """
    Wraps ChromaDB for storing and searching document chunks.

    Each chunk is stored as:
      - document: the chunk text
      - embedding: the vector (stored by ChromaDB automatically)
      - metadata: source file, domain, language, page number, etc.
      - id: unique identifier
    """

    def __init__(self, db_path: str = None, collection_name: str = None):
        db_path = db_path or os.getenv("CHROMA_DB_PATH", "./data/chroma_db")
        collection_name = collection_name or os.getenv(
            "CHROMA_COLLECTION", "digital_health_kb"
        )

        os.makedirs(db_path, exist_ok=True)

        # Persistent client — data survives between runs
        self.client = chromadb.PersistentClient(
            path=db_path,
            settings=Settings(anonymized_telemetry=False),
        )

        # Get or create the collection
        # (A collection = a named group of embeddings, like a table in SQL)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},  # cosine similarity for search
        )

        console.print(
            f"[green]✓ Vector store ready[/green] "
            f"[dim]({self.collection.count()} chunks already indexed)[/dim]"
        )

    def add_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> int:
        """
        Add chunks and their embeddings to the store.

        Returns the number of chunks actually added
        (skips duplicates based on source_file + chunk_index).
        """
        if not chunks:
            return 0

        # Build unique IDs — deterministic so re-ingesting the same file
        # doesn't create duplicates. Page number is included because chunk_index
        # resets to 0 on each page for multi-page PDFs.
        ids = [
            f"{chunk.source_file}__p{chunk.page_number or 0}__chunk_{chunk.chunk_index}"
            for chunk in chunks
        ]

        # Deduplicate IDs before querying (same chunk appearing twice in one batch)
        unique_ids = list(dict.fromkeys(ids))

        # Check which IDs already exist (to skip duplicates)
        existing = set(self.collection.get(ids=unique_ids)["ids"])
        new_indices = [i for i, id_ in enumerate(ids) if id_ not in existing]

        if not new_indices:
            console.print("[yellow]  All chunks already indexed — skipping[/yellow]")
            return 0

        # Filter to only new chunks
        new_chunks = [chunks[i] for i in new_indices]
        new_embeddings = [embeddings[i] for i in new_indices]
        new_ids = [ids[i] for i in new_indices]

        # ChromaDB batch add (max 5000 per call)
        batch_size = 500
        added = 0
        for i in range(0, len(new_chunks), batch_size):
            batch_chunks = new_chunks[i:i + batch_size]
            batch_embeddings = new_embeddings[i:i + batch_size]
            batch_ids = new_ids[i:i + batch_size]

            self.collection.add(
                ids=batch_ids,
                documents=[c.text for c in batch_chunks],
                embeddings=batch_embeddings,
                metadatas=[c.to_dict() for c in batch_chunks],
            )
            added += len(batch_chunks)

        return added

    def search(
        self,
        query_embedding: list[float],
        n_results: int = 5,
        filter_domain: Optional[str] = None,
        filter_language: Optional[str] = None,
    ) -> list[dict]:
        """
        Semantic search over the knowledge base.

        Args:
            query_embedding: The embedded search query
            n_results: Number of results to return
            filter_domain: Optional filter (e.g. "standards", "policy")
            filter_language: Optional filter (e.g. "en", "fr")

        Returns:
            List of dicts with keys: text, metadata, distance, score
        """
        # Build optional metadata filter
        where = {}
        if filter_domain:
            where["domain"] = filter_domain
        if filter_language:
            where["language"] = filter_language

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where if where else None,
            include=["documents", "metadatas", "distances"],
        )

        # Format results
        formatted = []
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        distances = results["distances"][0]

        for doc, meta, dist in zip(docs, metas, distances):
            formatted.append({
                "text": doc,
                "metadata": meta,
                "distance": dist,
                "score": round(1 - dist, 4),  # cosine similarity (1 = perfect match)
            })

        return formatted

    def search_with_sscp_priority(
        self,
        query_embedding: list[float],
        n_results: int = 5,
        sscp_slots: int = 2,
    ) -> list[dict]:
        """
        Search with SSCP content given priority slots.

        Retrieves up to `sscp_slots` chunks from SSCP documents first,
        then fills the remaining slots from the general knowledge base.
        SSCP chunks appear at the top of the context so the LLM sees them first.

        Args:
            query_embedding: Embedded query vector
            n_results:       Total chunks to return
            sscp_slots:      Max SSCP chunks to include (if available and relevant)

        Returns:
            Combined list — SSCP chunks first, then general KB chunks.
        """
        results = []
        seen_ids: set[str] = set()

        def _format(docs, metas, dists) -> list[dict]:
            out = []
            for doc, meta, dist in zip(docs, metas, dists):
                uid = f"{meta.get('source_file')}__p{meta.get('page_number', 0)}__c{meta.get('chunk_index', 0)}"
                if uid not in seen_ids:
                    seen_ids.add(uid)
                    out.append({
                        "text": doc,
                        "metadata": meta,
                        "distance": dist,
                        "score": round(1 - dist, 4),
                    })
            return out

        # ── Step 1: retrieve SSCP chunks ──────────────────────────────────────
        try:
            sscp_raw = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=sscp_slots,
                where={"sscp": "true"},
                include=["documents", "metadatas", "distances"],
            )
            results.extend(_format(
                sscp_raw["documents"][0],
                sscp_raw["metadatas"][0],
                sscp_raw["distances"][0],
            ))
        except Exception:
            # No SSCP chunks indexed yet — silently continue with general search
            pass

        # ── Step 2: fill remaining slots from general KB ──────────────────────
        remaining = n_results - len(results)
        if remaining > 0:
            # Fetch extra to account for deduplication against SSCP results
            general_raw = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results + sscp_slots,
                include=["documents", "metadatas", "distances"],
            )
            for item in _format(
                general_raw["documents"][0],
                general_raw["metadatas"][0],
                general_raw["distances"][0],
            ):
                results.append(item)
                if len(results) >= n_results:
                    break

        return results[:n_results]

    def stats(self) -> dict:
        """Return basic stats about the knowledge base."""
        total = self.collection.count()

        all_meta = self.collection.get(include=["metadatas"])["metadatas"]
        domains = {}
        languages = {}
        sscp_count = 0
        for m in all_meta:
            d = m.get("domain", "unknown")
            l = m.get("language", "unknown")
            domains[d] = domains.get(d, 0) + 1
            languages[l] = languages.get(l, 0) + 1
            if m.get("sscp") == "true":
                sscp_count += 1

        return {
            "total_chunks": total,
            "by_domain": domains,
            "by_language": languages,
            "sscp_chunks": sscp_count,
        }

    def has_source(self, source_file: str) -> bool:
        """Return True if this file has already been indexed."""
        results = self.collection.get(
            where={"source_file": source_file},
            limit=1,
            include=[],
        )
        return len(results["ids"]) > 0

    def delete_source(self, source_file: str) -> int:
        """Remove all chunks from a specific source file (for re-ingestion)."""
        results = self.collection.get(
            where={"source_file": source_file},
            include=[],
        )
        ids = results["ids"]
        if ids:
            self.collection.delete(ids=ids)
        return len(ids)
