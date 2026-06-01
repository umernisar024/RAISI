"""
llm_adapter.py — Unified LLM interface via LiteLLM.

Supports any provider by changing LLM_MODEL in .env — no code changes needed.

Provider model string examples (set as LLM_MODEL in .env):
  Anthropic Claude:   anthropic/claude-sonnet-4-6
  OpenAI:             openai/gpt-4o
  Azure OpenAI:       azure/my-deployment-name
  Ollama (local):     ollama/llama3
  AWS Bedrock:        bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0

See PROVIDERS.md for setup instructions for each provider.
"""

import os
from collections.abc import Generator
import litellm
from litellm import completion

# Suppress LiteLLM's verbose startup logging
litellm.suppress_debug_info = True


def get_model() -> str:
    return os.getenv("LLM_MODEL", "anthropic/claude-sonnet-4-6")


def _full_messages(system_prompt: str, messages: list[dict]) -> list[dict]:
    return [{"role": "system", "content": system_prompt}] + messages


def chat(
    system_prompt: str,
    messages: list[dict],
    max_tokens: int = 2048,
) -> str:
    """Blocking chat — returns the full response string."""
    response = completion(
        model=get_model(),
        messages=_full_messages(system_prompt, messages),
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content


def stream_chat(
    system_prompt: str,
    messages: list[dict],
    max_tokens: int = 2048,
) -> Generator[str, None, None]:
    """
    Streaming chat — yields text chunks as they arrive from the LLM.
    Falls back to a single-chunk yield if the provider doesn't support streaming.
    """
    try:
        response = completion(
            model=get_model(),
            messages=_full_messages(system_prompt, messages),
            max_tokens=max_tokens,
            stream=True,
        )
        for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    except Exception:
        # Fallback: non-streaming call yielded as one chunk
        yield chat(system_prompt, messages, max_tokens)
