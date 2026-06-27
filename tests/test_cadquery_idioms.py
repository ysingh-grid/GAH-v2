"""
Task 4 (deterministic): the auto-generated "verified CadQuery idioms" skill.

It must be (a) non-empty + bounded in size, (b) TRUTHFUL — every op signature it shows is a real KB
entry, and (c) explicitly list `taper` (the failing run's hallucination) as a method that does NOT
exist, verified against the live CadQuery API.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cadquery_kb_pack" / "tools"))

from cadquery_kb_tools import build_idioms_skill, KB


def test_idioms_skill_nonempty_and_bounded():
    skill = build_idioms_skill()
    assert skill, "idioms skill must be generated"
    assert 200 < len(skill) < 4000, f"compact skill should be small (~1KB), got {len(skill)} chars"
    # covers the core ops (bare names) + selectors
    for op in ("loft", "revolve", "sweep", "fillet"):
        assert op in skill, f"{op} missing from idioms skill"
    assert "SELECTORS" in skill and "|Z" in skill, "selector grammar missing"
    print(f"PASS idioms skill is compact ({len(skill)} chars) and covers core ops + selectors")


def test_idioms_skill_is_truthful():
    # the op names listed in the groups must be real KB methods; the does-not-exist entries must be
    # genuinely absent from the live CadQuery API.
    kb = KB()
    skill = build_idioms_skill()
    import re
    # group lines look like "3D build: box, cylinder, ..."; verify a few listed names are real KB ops
    for op in ("box", "cylinder", "loft", "revolve", "sweep", "fillet", "shell"):
        assert op in skill, f"{op} should be listed"
        assert op.lower() in kb._by_name, f"idioms skill lists '{op}' which is NOT a real KB op (untruthful)"
    # the DO NOT EXIST list must reference methods truly absent from live cadquery
    import cadquery as cq
    for m in re.findall(r"Workplane\.(\w+) ->", skill):
        assert not hasattr(cq.Workplane, m), f"'{m}' is listed as non-existent but EXISTS on Workplane"
    print("PASS listed ops are real KB methods; does-not-exist entries are genuinely absent (truthful)")


def test_taper_listed_as_nonexistent():
    skill = build_idioms_skill()
    assert "DO NOT EXIST" in skill, "missing the does-not-exist section"
    assert "Workplane.taper" in skill, "taper (the failing run's hallucination) must be flagged"
    import cadquery as cq
    assert not hasattr(cq.Workplane, "taper"), "sanity: Workplane.taper genuinely does not exist"
    print("PASS taper is flagged as non-existent (verified against live cadquery)")


if __name__ == "__main__":
    test_idioms_skill_nonempty_and_bounded()
    test_idioms_skill_is_truthful()
    test_taper_listed_as_nonexistent()
    print("\nALL CadQuery idioms-skill tests passed.")
