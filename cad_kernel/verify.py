"""
verify.py — the FIXED, deterministic MeshLib verification battery (the VERDICT).

This is authored by a human, runs identically on every solid, and the RLM does
NOT get to choose or skip its checks. The RLM may PROPOSE advisory checks
(run_advisory) which can flag concerns but NEVER override the verdict.

Why fixed: if the model that generated the geometry also chose how it is graded,
it would pass its own mistakes (the bug and the blind spot share a cause). A fixed
battery cannot be quietly steered around the very error that would catch it.

A passing verdict means SOUND + RIGHT-SIZED, not "the right object". Freeform
geometry therefore stays needs_review even when every check passes.
"""

import os
import tempfile

import cadquery as cq
from meshlib import mrmeshpy as mm
from meshlib.mrmeshpy import MeshPart

# tolerances for the declared-vs-measured bounding-box audit (meshing adds error)
BBOX_ABS_TOL = 0.6   # mm
BBOX_REL_TOL = 0.03  # 3%


def cq_to_meshlib(obj, tol: float = 0.01):
    """Bridge a CadQuery object (Workplane with one or many bodies, or a Solid) into a
    MeshLib mesh via a temporary STL. Normalizes to a clean compound so every body is
    exported (so assemblies measure all their parts)."""
    from cadquery import Compound
    if hasattr(obj, "vals"):
        shapes = []
        for v in obj.vals():
            shapes.append(v.val() if hasattr(v, "val") else v)
    elif hasattr(obj, "val"):
        shapes = [obj.val()]
    else:
        shapes = [obj]
    shapes = [s for s in shapes if s is not None]
    export_obj = shapes[0] if len(shapes) == 1 else Compound.makeCompound(shapes)
    f = tempfile.mktemp(suffix=".stl")
    cq.exporters.export(export_obj, f, tolerance=tol)
    try:
        return mm.loadMesh(f)
    finally:
        if os.path.exists(f):
            os.remove(f)


def measure(mesh) -> dict:
    """Deterministic intrinsic measurements of a mesh."""
    bb = mesh.computeBoundingBox()
    return {
        "volume": round(mesh.volume(), 4),
        "area": round(mesh.area(), 4),
        "bbox": [round(bb.max.x - bb.min.x, 4),
                 round(bb.max.y - bb.min.y, 4),
                 round(bb.max.z - bb.min.z, 4)],
        "watertight": mesh.topology.findHoleRepresentiveEdges().size() == 0,
        "components": int(mm.MeshComponents.getNumComponents(mesh)),
        "self_intersections": int(mm.findSelfCollidingTriangles(MeshPart(mesh)).size()),
    }


def _bbox_audit(meas, declared_bbox):
    """declared_bbox = [x, y, z] (any order); compare to measured sorted dims."""
    if not declared_bbox:
        return None, "no declared bbox to audit against"
    md = sorted(meas["bbox"])
    dd = sorted(float(v) for v in declared_bbox)
    ok = all(abs(a - b) <= max(BBOX_ABS_TOL, BBOX_REL_TOL * b) for a, b in zip(md, dd))
    return ok, f"measured {md} vs declared {dd} (sorted, tol {BBOX_ABS_TOL}mm/{int(BBOX_REL_TOL*100)}%)"


def verify_solid(solid, declared_bbox=None, expected_components: int = 1) -> dict:
    """Run the FIXED battery on a CadQuery solid. Returns measurements + per-check
    results + an overall deterministic verdict. expected_components > 1 for
    intentional multi-body assemblies."""
    mesh = cq_to_meshlib(solid)
    meas = measure(mesh)

    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    add("positive_volume", meas["volume"] > 0, f"volume = {meas['volume']} mm^3")
    add("watertight", meas["watertight"], "closed mesh (no boundary holes)" if meas["watertight"]
        else "OPEN mesh — boundary holes present")
    comp_ok = meas["components"] == expected_components
    add("component_count", comp_ok,
        f"{meas['components']} connected component(s), expected exactly {expected_components}")
    no_self_int = meas["self_intersections"] == 0
    add("no_self_intersections", no_self_int,
        f"{meas['self_intersections']} self-colliding triangle(s)")
    bbox_ok, bbox_detail = _bbox_audit(meas, declared_bbox)
    if bbox_ok is not None:
        add("bbox_matches_declared", bbox_ok, bbox_detail)

    facts_pass = all(c["passed"] for c in checks)
    # localized, actionable failure summary (for the repair loop)
    failures = [c for c in checks if not c["passed"]]
    return {
        "measurements": meas,
        "checks": checks,
        "facts_pass": facts_pass,
        "verdict": "PASS" if facts_pass else "FAIL",
        "localized_fix": (None if facts_pass else
                          "; ".join(f"{c['name']}: {c['detail']}" for c in failures)),
    }


def run_advisory(solid, fn_name: str, **kwargs) -> dict:
    """Run an RLM-PROPOSED measurement from MeshLib as an ADVISORY signal only.
    Never contributes to the verdict — it can flag a concern, not certify a pass.
    fn_name must be a callable on mrmeshpy or a method on the Mesh."""
    mesh = cq_to_meshlib(solid)
    target = getattr(mesh, fn_name, None) or getattr(mm, fn_name, None)
    if target is None:
        return {"advisory": fn_name, "ok": False, "error": "unknown MeshLib symbol"}
    try:
        val = target(mesh, **kwargs) if getattr(mm, fn_name, None) is target else target(**kwargs)
        return {"advisory": fn_name, "ok": True, "value": str(val)[:200],
                "note": "ADVISORY ONLY — does not affect the verdict"}
    except Exception as e:
        return {"advisory": fn_name, "ok": False, "error": str(e)[:200]}
