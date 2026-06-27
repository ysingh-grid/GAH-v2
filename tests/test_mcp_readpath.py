"""
Task 3 (deterministic, offline): the mcp_call read-path.

The engine's `mcp_call` returns the tool result as a JSON STRING (only sometimes a dict), so the
agent MUST parse it. The old contract said "the return IS the result", which made the agent call
`.get`/`[...]` on a string and crash ('str' object has no attribute 'get') — its FINAL branch was
unreachable for the entire failing run. These tests assert the robust idiom works for BOTH a string
and a dict, and that the misleading text is gone from the prompt/contract.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _parse(r):
    # the exact robust idiom documented in core.md + orchestrator task instructions
    return json.loads(r) if isinstance(r, str) else r


def test_parse_handles_string_and_dict():
    # build_verify_render normally comes back as a JSON STRING:
    s = '{"verdict": "PASS", "verification_token": "abc123", "trust_tier": "needs_review"}'
    v = _parse(s)
    assert isinstance(v, dict) and v["verdict"] == "PASS", v
    assert v["verification_token"] == "abc123", v
    # ...but if structuredContent is present, mcp_call returns a dict — the idiom passes it through:
    d = {"verdict": "PASS", "verification_token": "xyz"}
    assert _parse(d) is d, "dict must pass through unchanged"
    print("PASS robust parse idiom reads verdict/token from BOTH a string and a dict")


def test_contract_text_fixed():
    core = (ROOT / "skills" / "core.md").read_text(encoding="utf-8")
    orch = (ROOT / "orchestrator.py").read_text(encoding="utf-8")
    assert "the return IS the result" not in core, "core.md still has the misleading contract line"
    assert "json.loads(r) if isinstance(r, str) else r" in core, "core.md missing the robust parse idiom"
    assert "json.loads(r) if isinstance(r, str) else r" in orch, "task instructions missing the parse idiom"
    print("PASS contract text fixed in core.md + orchestrator (parse rule present, misleading line gone)")


if __name__ == "__main__":
    test_parse_handles_string_and_dict()
    test_contract_text_fixed()
    print("\nALL mcp read-path tests passed.")
