"""Tests for tools/gemini_client.py — the thinking_config fallback (no live API)."""

from __future__ import annotations

import pytest


def _install_fake_genai(monkeypatch, calls, *, thinking_raises=True):
    """Patch google.genai.Client so generate_content records whether thinking_config
    was sent and (optionally) raises a thinking-400 when it was."""
    from google import genai

    class _Resp:
        def __init__(self, text: str) -> None:
            self.text = text

    class _Models:
        def generate_content(self, *, model, contents, config):  # noqa: ANN001
            has_thinking = getattr(config, "thinking_config", None) is not None
            calls.append(has_thinking)
            if has_thinking and thinking_raises:
                raise RuntimeError(
                    "400 INVALID_ARGUMENT: Thinking level is not supported for this model."
                )
            return _Resp('{"ok": true}')

    class _Client:
        def __init__(self, **_kw) -> None:
            self.models = _Models()

    monkeypatch.setattr(genai, "Client", _Client)


def test_drops_thinking_on_unsupported_400_and_caches(monkeypatch):
    import tools.gemini_client as gc

    gc._THINKING_UNSUPPORTED.clear()
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    calls: list[bool] = []
    _install_fake_genai(monkeypatch, calls)

    out = gc.generate_content_text(
        model="m1", contents=["c"], system_instruction="s", max_output_tokens=100, thinking="low"
    )
    assert out == '{"ok": true}'
    assert calls == [True, False]  # tried WITH thinking, then retried WITHOUT
    assert "m1" in gc._THINKING_UNSUPPORTED  # cached so future calls skip thinking


def test_second_call_skips_thinking_directly(monkeypatch):
    import tools.gemini_client as gc

    gc._THINKING_UNSUPPORTED.clear()
    gc._THINKING_UNSUPPORTED.add("m1")  # already known-bad
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    calls: list[bool] = []
    _install_fake_genai(monkeypatch, calls)

    out = gc.generate_content_text(
        model="m1", contents=["c"], system_instruction="s", max_output_tokens=100, thinking="low"
    )
    assert out == '{"ok": true}'
    assert calls == [False]  # exactly one call, no thinking, no wasted 400


def test_non_thinking_error_reraises(monkeypatch):
    import tools.gemini_client as gc

    gc._THINKING_UNSUPPORTED.clear()
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    from google import genai

    class _Models:
        def generate_content(self, **_kw):  # noqa: ANN003
            raise RuntimeError("500 internal server error")

    class _Client:
        def __init__(self, **_kw) -> None:
            self.models = _Models()

    monkeypatch.setattr(genai, "Client", _Client)
    with pytest.raises(RuntimeError, match="500 internal"):
        gc.generate_content_text(
            model="m1", contents=["c"], system_instruction="s", max_output_tokens=100
        )


def test_missing_api_key_raises(monkeypatch):
    import tools.gemini_client as gc

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        gc.generate_content_text(
            model="m", contents=[], system_instruction="s", max_output_tokens=10
        )
