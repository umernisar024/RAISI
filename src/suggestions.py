"""
suggestions.py — Generates alternative question suggestions when the KB can't answer.

When the RAG chatbot returns "I could not find relevant information", this module
uses the retrieved chunks (which ARE topically related, just not specific enough)
to generate 4 alternative questions that the KB CAN answer.

Only fires on the failure path — no extra cost on successful answers.
"""

import json
from src.llm_adapter import chat as llm_chat

# Phrases that indicate the model could not answer from the retrieved context.
# The model doesn't always use the exact system-prompt phrase, so we match
# a broader set of refusal patterns.
_NOT_FOUND_PHRASES = [
    "could not find relevant information",
    "not enough information",
    "not enough context",
    "doesn't have enough context",
    "does not have enough context",
    "cannot find",
    "could not find",
    "retrieved context does not contain",
    "context does not contain",
    "outside the scope",
    "not within the scope",
    "unable to answer",
    "cannot answer",
    "no information available",
    "knowledge base does not",
    "not covered in",
    "don't have information",
    "do not have information",
]

SUGGESTION_SYSTEM_PROMPT = """You are helping a user of a digital health standards and interoperability knowledge base refine their question.

The user asked something the knowledge base could not fully answer. However, related content WAS retrieved. Your job is to suggest 4 specific, answerable questions based on what IS in that content.

Rules:
- Each suggestion must be directly answerable from the provided context snippets
- Keep suggestions specific and actionable — not vague generalities
- Stay within digital health, interoperability, and health standards
- Vary the suggestions — cover different aspects visible in the content
- Each question should be 10–20 words
- Return ONLY a valid JSON array of exactly 4 strings, no other text"""


def is_not_found(response_text: str) -> bool:
    """Return True if the response is a 'not found' refusal."""
    lower = response_text.lower()
    return any(phrase in lower for phrase in _NOT_FOUND_PHRASES)


def generate_suggestions(original_question: str, retrieved_chunks: list[dict]) -> list[str]:
    """
    Generate 4 alternative questions grounded in what the KB actually contains.

    Args:
        original_question:  The question the user asked that couldn't be answered.
        retrieved_chunks:   The chunks returned by the RAG pipeline for that question.
                            Even though they didn't answer the question, they show
                            what nearby content IS available.

    Returns:
        List of 4 question strings, or [] if generation fails.
    """
    if not retrieved_chunks:
        return []

    # Condense chunk content — enough for the LLM to see what topics are covered
    chunk_summaries = []
    for i, chunk in enumerate(retrieved_chunks[:4], 1):
        text = chunk.get("text", "")[:350].replace("\n", " ")
        source = chunk.get("metadata", {}).get("source_file", "unknown")
        is_sscp = chunk.get("metadata", {}).get("sscp") == "true"
        label = "SSCP field experience" if is_sscp else source
        chunk_summaries.append(f"[{i}: {label}] {text}")

    context = "\n\n".join(chunk_summaries)

    user_message = (
        f'The user asked: "{original_question}"\n\n'
        f"The knowledge base retrieved these related excerpts but could not fully answer:\n\n"
        f"{context}\n\n"
        f"Based on what IS in these excerpts, suggest 4 specific questions the user "
        f"could ask that would get a good answer. Return only a JSON array of 4 strings."
    )

    try:
        response = llm_chat(
            system_prompt=SUGGESTION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=400,
        )

        # Strip markdown code fences if the LLM wraps the JSON
        clean = response.strip()
        if clean.startswith("```"):
            clean = "\n".join(clean.split("\n")[1:])
        if "```" in clean:
            clean = clean[:clean.index("```")]

        suggestions = json.loads(clean.strip())

        if isinstance(suggestions, list):
            return [str(s).strip() for s in suggestions[:4] if str(s).strip()]

        return []

    except Exception:
        return []
