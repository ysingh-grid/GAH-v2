"""Unit tests for backend/web_search/store.py — no network, injected client."""

from backend.web_search import store


class _Web:
    def __init__(self, title: str, uri: str) -> None:
        self.title = title
        self.uri = uri


class _Chunk:
    def __init__(self, web: object) -> None:
        self.web = web


class _Meta:
    def __init__(self, chunks: list) -> None:
        self.grounding_chunks = chunks


class _Candidate:
    def __init__(self, meta: object) -> None:
        self.grounding_metadata = meta


class _Response:
    def __init__(self, text: str, candidates: list) -> None:
        self.text = text
        self.candidates = candidates


class _Models:
    def __init__(self, response: object) -> None:
        self._response = response

    def generate_content(self, **_kwargs: object) -> object:
        return self._response


class _FakeClient:
    def __init__(self, response: object) -> None:
        self.models = _Models(response)


def test_search_returns_answer_and_sources():
    response = _Response(
        text="Standard DIN rail width is 35 mm.",
        candidates=[_Candidate(_Meta([_Chunk(_Web("DIN 46277", "https://example.com/din"))]))],
    )
    out = store.search_measurements("DIN rail width", client=_FakeClient(response))
    assert out["query"] == "DIN rail width"
    assert "35 mm" in out["answer"]
    assert out["sources"] == [{"title": "DIN 46277", "uri": "https://example.com/din"}]


def test_search_with_no_candidates_returns_empty_sources():
    out = store.search_measurements("anything", client=_FakeClient(_Response("ans", [])))
    assert out["answer"] == "ans"
    assert out["sources"] == []


def test_search_without_api_key_returns_error_not_crash(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    out = store.search_measurements("x")  # client builds from env -> None
    assert out["answer"] == ""
    assert "error" in out


def test_search_swallows_client_exception(monkeypatch):
    class _Boom:
        @property
        def models(self):
            raise RuntimeError("network down")

    out = store.search_measurements("x", client=_Boom())
    assert out["answer"] == ""
    assert "search failed" in out["error"]
