"""Gemini Google-Search grounding — the engine behind the RLM's web_search tool.

`search_measurements` issues a grounded Gemini request and returns a synthesized
answer plus its web sources. The Gemini client is injectable so tests can run
without network or an API key.
"""

from __future__ import annotations

import os
from typing import Any, Protocol, cast


class _GenAIClient(Protocol):
    """Minimal shape of the google-genai client we depend on (for typing/mocks)."""

    models: Any


def _extract_sources(response: object) -> list[dict[str, str]]:
    """Pull {title, uri} web sources out of a grounded response (defensively)."""
    sources: list[dict[str, str]] = []
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        metadata = getattr(candidate, "grounding_metadata", None)
        chunks = getattr(metadata, "grounding_chunks", None) or []
        for chunk in chunks:
            web = getattr(chunk, "web", None)
            if web is None:
                continue
            uri = getattr(web, "uri", "") or ""
            title = getattr(web, "title", "") or uri
            if uri:
                sources.append({"title": title, "uri": uri})
    return sources


def _build_default_client() -> _GenAIClient | None:
    """Construct a real google-genai client from the env, or None if no key."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key or api_key.startswith("your-"):
        return None
    from google import genai

    # google-genai is untyped at this boundary; the Protocol captures what we use.
    return cast(_GenAIClient, genai.Client(api_key=api_key))


def search_measurements(
    query: str,
    *,
    client: _GenAIClient | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Search the web for a measurement / standard via Gemini grounding.

    Args:
        query: Natural-language question, e.g. "standard DIN rail width mm".
        client: Optional google-genai client (injected in tests). Built from
            GEMINI_API_KEY when omitted.
        model: Optional model id; defaults to env GEMINI_SEARCH_MODEL or a flash
            model.

    Returns:
        {"query", "answer", "sources": [{"title", "uri"}]}. On a missing key or
        a transport error, "answer" is "" and an "error" key explains why — the
        caller (and the RLM) treats that as "no result", never a crash.
    """
    model = model or os.getenv("GEMINI_SEARCH_MODEL") or "gemini-2.5-flash"
    if client is None:
        client = _build_default_client()
    if client is None:
        return {"query": query, "answer": "", "sources": [], "error": "GEMINI_API_KEY not set"}

    try:
        from google.genai import types

        config = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())])
        response = client.models.generate_content(model=model, contents=query, config=config)
        return {
            "query": query,
            "answer": getattr(response, "text", "") or "",
            "sources": _extract_sources(response),
        }
    except Exception as exc:  # noqa: BLE001 — never crash the tool; report and move on
        return {"query": query, "answer": "", "sources": [], "error": f"search failed: {exc}"}
