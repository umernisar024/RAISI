"""
chat.py — RAG chatbot core.

Retrieves relevant chunks from the knowledge base, builds a grounded prompt,
and calls the configured LLM to generate an answer with source citations.

The LLM provider is set via LLM_MODEL in .env — see PROVIDERS.md.
Synonym expansion is configured via data/synonyms.json — edit without code changes.
"""

import os
import json
import re
from pathlib import Path
from src.embedder import Embedder
from src.store import VectorStore
from src.llm_adapter import chat as llm_chat, stream_chat as llm_stream

DEFAULT_SYSTEM_PROMPT_PATH = Path("./data/system_prompt.txt")
DEFAULT_SYNONYMS_PATH = Path("./data/synonyms.json")

FALLBACK_SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer questions based on the provided context. "
    "Cite sources where relevant. If the context does not contain enough information, say so."
)

# How many recent conversation turns to blend into the retrieval query.
RETRIEVAL_HISTORY_TURNS = int(os.getenv("RETRIEVAL_HISTORY_TURNS", "2"))


def load_system_prompt(path: Path = DEFAULT_SYSTEM_PROMPT_PATH) -> str:
    """Load system prompt from file, falling back to the built-in default."""
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return FALLBACK_SYSTEM_PROMPT


def load_synonyms(path: Path = DEFAULT_SYNONYMS_PATH) -> dict[str, list[str]]:
    """
    Load synonym mappings from data/synonyms.json.
    Returns empty dict if file not found — synonym expansion is silently skipped.
    """
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # Strip the comment key if present
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception:
        return {}


def expand_query(query: str, synonyms: dict[str, list[str]]) -> str:
    """
    Expand a query with synonyms so ChromaDB retrieves chunks that use
    different terminology for the same concept.

    Example:
        query   = "what is DPI-H"
        returns = "what is DPI-H Health Information Exchange interoperability layer
                   health data exchange HIE"

    Only appends synonyms — never replaces the original terms so the
    user's exact phrasing is always included in the search.
    """
    if not synonyms:
        return query

    appended = set()
    query_lower = query.lower()

    for term, equivalents in synonyms.items():
        # Match whole word / phrase, case-insensitive
        pattern = r"(?<!\w)" + re.escape(term) + r"(?!\w)"
        if re.search(pattern, query, flags=re.IGNORECASE):
            for eq in equivalents:
                if eq.lower() not in query_lower and eq not in appended:
                    appended.add(eq)

    if appended:
        return query + " " + " ".join(appended)
    return query


class RAGChat:
    def __init__(
        self,
        system_prompt: str | None = None,
        embedder: Embedder | None = None,
        store: VectorStore | None = None,
    ):
        # Accept pre-loaded shared instances (e.g. cached by Streamlit)
        # to avoid reloading the model on every new session.
        self.embedder = embedder or Embedder()
        self.store = store or VectorStore()
        self.n_results = int(os.getenv("RAG_N_RESULTS", "5"))
        self.history: list[dict] = []
        self.system_prompt = system_prompt or load_system_prompt()
        self.synonyms = load_synonyms()

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def _contextual_query(self, user_message: str) -> str:
        """
        Blend the current question with recent conversation history so that
        follow-up questions like "tell me more" or "what about SNOMED then"
        retrieve the right chunks even without explicit topic keywords.
        """
        if not self.history:
            return user_message

        user_turns = [
            m["content"] for m in self.history
            if m["role"] == "user"
        ][-RETRIEVAL_HISTORY_TURNS:]

        if not user_turns:
            return user_message

        context_prefix = " | ".join(user_turns)
        return f"{context_prefix} | {user_message}"

    def retrieve(self, user_message: str) -> list[dict]:
        # Step 1: add conversation context
        query = self._contextual_query(user_message)
        # Step 2: expand with synonyms so alternate terminology gets retrieved
        query = expand_query(query, self.synonyms)
        embedding = self.embedder.embed_query(query)
        # Step 3: priority search — SSCP content fills first slots if relevant
        return self.store.search_with_sscp_priority(
            embedding,
            n_results=self.n_results,
            sscp_slots=2,   # up to 2 of N results reserved for SSCP content
        )

    # Friendly display names for internal reference files shown to the LLM.
    _SOURCE_ALIASES = {
        "glossary.md": "Domain Glossary",
    }

    def _build_context(self, results: list[dict]) -> str:
        parts = []
        for i, r in enumerate(results, 1):
            meta = r["metadata"]
            source = meta.get("source_file", "unknown")
            source = self._SOURCE_ALIASES.get(source, source)
            is_sscp = meta.get("sscp") == "true"
            label = "SSCP Source" if is_sscp else "Source"
            page = meta.get("page_number")
            loc = f", page {page}" if page else ""
            parts.append(f"[{label} {i}: {source}{loc}]\n{r['text']}")
        return "\n\n---\n\n".join(parts)

    # ── Chat ──────────────────────────────────────────────────────────────────

    def chat(self, user_message: str) -> tuple[str, list[dict]]:
        """
        Send a message and get a RAG-grounded response.

        Returns:
            answer:  The LLM's response string.
            sources: Retrieved chunk dicts (for display/citation).
        """
        sources = self.retrieve(user_message)
        context = self._build_context(sources)

        augmented = (
            f"<retrieved_context>\n{context}\n</retrieved_context>\n\n"
            f"<user_question>\n{user_message}\n</user_question>"
        )

        messages = self.history + [{"role": "user", "content": augmented}]

        answer = llm_chat(
            system_prompt=self.system_prompt,
            messages=messages,
        )

        self.history.append({"role": "user", "content": user_message})
        self.history.append({"role": "assistant", "content": answer})

        return answer, sources

    def stream_chat(self, user_message: str) -> tuple[list[dict], object]:
        """
        Streaming chat — retrieves sources immediately, then streams the LLM response.

        Returns:
            sources:    Retrieved chunk dicts (for citation display).
            generator:  Text-chunk generator to pass to st.write_stream() or iterate.

        Call add_to_history() after the generator is fully consumed.
        """
        sources = self.retrieve(user_message)
        context = self._build_context(sources)

        # XML-style tags provide stronger structural separation between retrieved
        # document content and the user's question.  This makes it harder for
        # injected instructions inside a document chunk to be mistaken for a
        # system directive or a new user turn by the LLM.
        augmented = (
            f"<retrieved_context>\n{context}\n</retrieved_context>\n\n"
            f"<user_question>\n{user_message}\n</user_question>"
        )
        messages = self.history + [{"role": "user", "content": augmented}]
        generator = llm_stream(system_prompt=self.system_prompt, messages=messages)
        return sources, generator

    def add_to_history(self, user_message: str, answer: str) -> None:
        """Save a completed exchange to conversation history after streaming."""
        self.history.append({"role": "user", "content": user_message})
        self.history.append({"role": "assistant", "content": answer})

    def reset(self):
        """Clear conversation history (start a new session)."""
        self.history = []
