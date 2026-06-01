"""
chunker.py — Splits documents into overlapping chunks for embedding.

Why chunking matters:
  - Embedding models have a max input length (~512 tokens)
  - Smaller chunks = more precise retrieval
  - Overlap between chunks = no context lost at boundaries
"""

import re
from dataclasses import dataclass
from typing import Optional
from langchain_text_splitters import RecursiveCharacterTextSplitter
import tiktoken


@dataclass
class Chunk:
    """One chunk of text with its metadata."""
    text: str
    source_file: str
    page_number: Optional[int]
    chunk_index: int
    total_chunks: int
    domain: str          # e.g. "standards", "policy", "case_study"
    language: str        # e.g. "en", "fr", "pt"
    token_count: int
    sscp: bool = False   # True = from SSCP project knowledge base (priority retrieval)

    def to_dict(self) -> dict:
        """Convert to dict for ChromaDB storage."""
        return {
            "source_file": self.source_file,
            "page_number": self.page_number or 0,
            "chunk_index": self.chunk_index,
            "total_chunks": self.total_chunks,
            "domain": self.domain,
            "language": self.language,
            "token_count": self.token_count,
            "sscp": "true" if self.sscp else "false",  # ChromaDB stores as string
        }


def count_tokens(text: str, model: str = "cl100k_base") -> int:
    """Count tokens in a string using tiktoken."""
    enc = tiktoken.get_encoding(model)
    return len(enc.encode(text))


def detect_language(text: str) -> str:
    """
    Simple language detection based on common words.
    For production, use `langdetect` or `fasttext`.
    """
    sample = text[:500].lower()
    if any(w in sample for w in ["le ", "la ", "les ", "des ", "est ", "une "]):
        return "fr"
    if any(w in sample for w in ["da ", "do ", "que ", "para ", "uma ", "com "]):
        return "pt"
    if any(w in sample for w in ["ya ", "na ", "kwa ", "wa ", "ni ", "au "]):
        return "sw"  # Swahili
    return "en"


def infer_domain(filename: str, text: str) -> str:
    """
    Infer the knowledge domain from filename and content.
    This drives which sub-agent will use this chunk later.
    """
    filename_lower = filename.lower()
    text_lower = text[:300].lower()

    if any(k in filename_lower for k in ["hl7", "fhir", "ihe", "icd", "snomed", "loinc"]):
        return "standards"
    if any(k in filename_lower for k in ["who", "guideline", "policy", "strategy", "national"]):
        return "policy"
    if any(k in filename_lower for k in ["case", "report", "implementation", "deploy"]):
        return "case_study"
    if any(k in filename_lower for k in ["dhis2", "openmrs", "bahmni", "commcare", "rapidpro"]):
        return "open_source_tools"
    if any(k in filename_lower for k in ["pepfar", "usaid", "global_fund", "gavi", "donor"]):
        return "donor_frameworks"
    if any(k in text_lower for k in ["fhir", "hl7", "interoperab"]):
        return "standards"
    if any(k in text_lower for k in ["guideline", "recommendation", "policy"]):
        return "policy"
    return "general"


class DocumentChunker:
    """
    Splits raw document text into overlapping chunks.

    Uses LangChain's RecursiveCharacterTextSplitter, which tries to split
    at natural boundaries: paragraphs → sentences → words.
    """

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # RecursiveCharacterTextSplitter tries each separator in order,
        # falling back to the next if the chunk is still too large.
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size * 4,   # approx chars (4 chars ≈ 1 token)
            chunk_overlap=chunk_overlap * 4,
            separators=["\n\n", "\n", ". ", " ", ""],
            length_function=len,
        )

    def chunk_document(
        self,
        text: str,
        source_file: str,
        page_number: Optional[int] = None,
        sscp: bool = False,
        domain: Optional[str] = None,
    ) -> list[Chunk]:
        """
        Split a document's text into Chunk objects.

        Args:
            text:        Raw text content of the document
            source_file: Filename (used for metadata + domain inference)
            page_number: Optional page number (for PDFs)
            sscp:        True if from the SSCP priority knowledge base
            domain:      Explicit KB subfolder name (e.g. "who_guidelines").
                         If not provided, domain is inferred from filename/content.

        Returns:
            List of Chunk objects ready for embedding
        """
        # Clean the text
        text = self._clean_text(text)

        if not text.strip():
            return []

        # Split into raw text chunks
        raw_chunks = self.splitter.split_text(text)

        # Detect language; use explicit domain if provided, otherwise infer
        language = detect_language(text)
        resolved_domain = domain if domain else infer_domain(source_file, text)

        chunks = []
        for i, chunk_text in enumerate(raw_chunks):
            chunk_text = chunk_text.strip()
            if len(chunk_text) < 50:  # skip very short chunks
                continue

            chunks.append(Chunk(
                text=chunk_text,
                source_file=source_file,
                page_number=page_number,
                chunk_index=i,
                total_chunks=len(raw_chunks),
                domain=resolved_domain,
                language=language,
                token_count=count_tokens(chunk_text),
                sscp=sscp,
            ))

        return chunks

    def _clean_text(self, text: str) -> str:
        """Remove junk characters common in PDF extraction."""
        # Collapse multiple blank lines
        text = re.sub(r'\n{3,}', '\n\n', text)
        # Remove null bytes
        text = text.replace('\x00', '')
        # Remove excessive spaces
        text = re.sub(r' {3,}', ' ', text)
        return text.strip()
