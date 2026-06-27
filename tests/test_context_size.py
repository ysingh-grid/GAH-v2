"""
Fix C / C5 (deterministic): the agent's role_instructions must stay COMPACT so it reads them in a
couple of cheap steps and spends its call budget BUILDING — not re-reading (the 50-step run burned
~36 steps reading before its first build). This caps the assembled context size while asserting the
load-bearing contract tokens are still present (capability preserved, not gutted).
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cadquery_kb_pack" / "tools"))
os.environ.setdefault("PRIMITIVES_JSON_DATA", (ROOT / "schemas" / "primitives.json").read_text())
os.environ.setdefault("RLM_MODEL_API_KEY", "dummy")

import orchestrator as orch                      # noqa: E402
from cadquery_kb_tools import build_idioms_skill  # noqa: E402

CAP = 30000  # chars — bounds runaway bloat (was ~33KB; idioms skill cut ~6KB). The real behavioral
             # fix is the front-loaded START-HERE block (build early, don't re-read) + the compact
             # idioms skill; core.md + the primitive catalog are high-value and deliberately NOT gutted.


def _assembled_role_instructions():
    core = (ROOT / "skills" / "core.md").read_text(encoding="utf-8").strip()
    summary = orch.generate_primitives_summary() or ""
    idioms = build_idioms_skill() or ""
    return f"{core}\n{summary}\n\n{idioms}"


def test_role_instructions_bounded():
    role = _assembled_role_instructions()
    assert len(role) < CAP, f"role_instructions is {len(role)} chars (> {CAP}); compress to keep the " \
                            "agent from burning its budget reading"
    print(f"PASS assembled role_instructions is {len(role)} chars (< {CAP})")


def test_role_instructions_still_complete():
    role = _assembled_role_instructions()
    for token in ("verification_token", "attach", "build_verify", "assembly", "taper"):
        assert token in role, f"compression dropped a load-bearing token: {token!r}"
    print("PASS compact context still contains the load-bearing contract (token/attach/build_verify/assembly/taper)")


def test_monolithic_fusion_capability_surfaced():
    """The general monolithic-fusion path (the impeller class) must be DISCOVERABLE in the
    front-loaded context — the twisted_loft technique + the radial-pattern-fuse recipe — so the
    agent reaches it fast. This is a FACTUAL capability statement, not behavior scripting."""
    role = _assembled_role_instructions()
    for token in ("twisted_loft", "single_solid", "radial"):
        assert token in role, f"the monolithic-fusion capability must stay surfaced: {token!r}"
    idioms = build_idioms_skill()
    assert "twisted_loft" in idioms and "pattern" in idioms, \
        "the idioms cheat-sheet must surface twisted_loft + the radial pattern fuse"
    print("PASS monolithic-fusion capability (twisted_loft + radial pattern + single_solid) is surfaced")


def test_idioms_skill_is_compact():
    assert len(build_idioms_skill()) < 4000, "idioms skill must be compact (~1KB)"
    print("PASS idioms skill is compact")


if __name__ == "__main__":
    test_role_instructions_bounded()
    test_role_instructions_still_complete()
    test_monolithic_fusion_capability_surfaced()
    test_idioms_skill_is_compact()
    print("\nALL context-size tests passed.")
