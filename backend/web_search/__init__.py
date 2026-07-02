"""Web-search service: host-side Gemini Google-Search grounding for the RLM.

The RLM runs in a Pyodide sandbox and cannot call google-genai directly, so it
hits this read-only door over HTTP; the grounding call happens here on the host
where GEMINI_API_KEY lives.
"""
