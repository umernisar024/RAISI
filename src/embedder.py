"""
embedder.py — Converts text chunks into vector embeddings.

Default model: all-MiniLM-L6-v2 (English, fast, ~90MB)

To switch to multilingual, set in .env:
  EMBEDDING_MODEL=intfloat/multilingual-e5-small   # fast, 100+ languages
  EMBEDDING_MODEL=intfloat/multilingual-e5-large   # slower, best quality

NOTE: e5 models require "query: " / "passage: " prefixes — this is handled
automatically based on the model name. Other models do not use prefixes.
"""

import os
from sentence_transformers import SentenceTransformer
from rich.console import Console

console = Console()

# Models that require query/passage prefixes
E5_MODELS = ("e5-small", "e5-base", "e5-large", "e5-mistral")


class Embedder:
    def __init__(self, model_name: str = None):
        model_name = model_name or os.getenv(
            "EMBEDDING_MODEL",
            "all-MiniLM-L6-v2"
        )

        console.print(f"[dim]Loading embedding model: {model_name}[/dim]")
        console.print("[dim](First run downloads model — subsequent runs are instant)[/dim]")

        self.model = SentenceTransformer(model_name)
        self.model_name = model_name
        self.dimension = self.model.get_sentence_embedding_dimension()

        # e5 models need explicit prefixes; standard models do not
        self.use_prefix = any(tag in model_name for tag in E5_MODELS)

        console.print(
            f"[green]✓ Embedding model loaded[/green] "
            f"[dim](dim: {self.dimension}, "
            f"prefixes: {'yes' if self.use_prefix else 'no'})[/dim]"
        )

    def _prefix(self, texts: list[str], kind: str) -> list[str]:
        """Add query/passage prefix only for models that need it."""
        if not self.use_prefix:
            return texts
        return [f"{kind}: {t}" for t in texts]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed document passages for indexing."""
        inputs = self._prefix(texts, "passage")
        embeddings = self.model.encode(
            inputs,
            batch_size=64,
            show_progress_bar=True,
            normalize_embeddings=True,
        )
        return embeddings.tolist()

    def embed_query(self, query: str) -> list[float]:
        """Embed a single search query."""
        inputs = self._prefix([query], "query")
        embedding = self.model.encode(
            inputs[0],
            normalize_embeddings=True,
        )
        return embedding.tolist()
