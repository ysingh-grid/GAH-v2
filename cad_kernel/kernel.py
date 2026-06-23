"""
kernel.py — deterministic execution of a GeometryPlan into a CadQuery solid.

Determinism lives HERE (and in verify.py), not in the LLM that wrote the plan:
- primitive steps build from the FIXED templates in primitives.json (no generation);
- custom steps run their code_sketch in an ISOLATED subprocess with a timeout;
- steps are positioned (position/rotation) and combined (operation) the same way
  every time. Same plan in -> same solid out.

Returns a result object carrying the solid and a per-step status so the repair
loop knows exactly which step failed and why (actionable, not "invalid").
"""

import json
import math
import os
import sys
import tempfile
from pathlib import Path

import cadquery as cq

ROOT = Path(__file__).resolve().parent.parent
_PRIM_PATH = ROOT / "schemas" / "primitives.json"
_PRIMS = json.loads(_PRIM_PATH.read_text()) if _PRIM_PATH.exists() else {}

CUSTOM_TIMEOUT_S = int(os.environ.get("CUSTOM_STEP_TIMEOUT", 30))


def _primitive_solid(ptype: str, params: dict):
    """Build a primitive from its FIXED template, filling defaults for missing keys."""
    spec = _PRIMS.get(ptype)
    if not spec:
        raise ValueError(f"unknown primitive_type '{ptype}'")
    merged = {k: v.get("default") for k, v in spec.get("parameters", {}).items()}
    merged.update(params or {})
    template = spec["template"]
    expr = template.format(**merged)
    return eval(expr, {"cq": cq, "math": math})  # template is trusted (from primitives.json)


def _custom_solid(params: dict):
    """Execute an LLM-authored code_sketch in an ISOLATED subprocess with a timeout,
    transferring the result as a true BREP so later boolean ops stay exact.
    Robust regardless of how the parent process was launched."""
    code = params.get("code_sketch") or params.get("code") or ""
    if not code.strip():
        raise ValueError("custom step has no code_sketch")

    import subprocess
    runner = str(Path(__file__).resolve().parent / "_custom_runner.py")
    code_file = tempfile.mktemp(suffix=".py")
    out_brep = tempfile.mktemp(suffix=".brep")
    Path(code_file).write_text(code, encoding="utf-8")
    try:
        proc = subprocess.run([sys.executable, runner, code_file, out_brep],
                              capture_output=True, text=True, timeout=CUSTOM_TIMEOUT_S)
        if proc.returncode != 0:
            raise RuntimeError("custom code_sketch failed: "
                               + (proc.stderr.strip() or f"exit {proc.returncode}"))
        if not os.path.exists(out_brep):
            raise RuntimeError("custom step produced no solid (did the code bind `result`?)")
        from OCP.BRepTools import BRepTools
        from OCP.BRep import BRep_Builder
        from OCP.TopoDS import TopoDS_Shape
        shape = TopoDS_Shape()
        BRepTools.Read_s(shape, out_brep, BRep_Builder())
        return cq.Workplane("XY").add(cq.Shape.cast(shape))
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"custom step timed out after {CUSTOM_TIMEOUT_S}s "
                           "(possible infinite loop or excessively expensive geometry)")
    finally:
        for f in (code_file, out_brep):
            if os.path.exists(f):
                os.remove(f)


_ANCHOR_SEL = {"top": ">Z", "bottom": "<Z", "right": ">X", "left": "<X", "back": ">Y", "front": "<Y"}
_ANCHOR_DIR = {"top": (0, 0, 1), "bottom": (0, 0, -1), "right": (1, 0, 0), "left": (-1, 0, 0),
               "back": (0, 1, 0), "front": (0, -1, 0), "center": (0, 0, 0)}
_OPPOSITE = {"top": "bottom", "bottom": "top", "left": "right", "right": "left",
             "front": "back", "back": "front", "center": "center"}


def _as_wp(obj):
    """Normalize a template/eval result to a Workplane for boolean ops."""
    if isinstance(obj, cq.Workplane):
        return obj
    return cq.Workplane("XY").add(obj)


def _rotate(wp, rotation):
    """Apply X, then Y, then Z rotations (degrees) about the global origin, in the
    part's local frame (before any translation)."""
    if rotation and any(rotation):
        rx, ry, rz = (list(rotation) + [0, 0, 0])[:3]
        for ang, (a, b) in ((rx, ((0, 0, 0), (1, 0, 0))),
                            (ry, ((0, 0, 0), (0, 1, 0))),
                            (rz, ((0, 0, 0), (0, 0, 1)))):
            if ang:
                wp = wp.rotate(a, b, ang)
    return wp


def _place_absolute(wp, position, rotation):
    """Absolute placement convention: translate (local frame) THEN rotate about the
    origin — keeps radial patterns intuitive (translate out +X, rotate about Z)."""
    if position and any(position):
        x, y, z = (list(position) + [0, 0, 0])[:3]
        wp = wp.translate((x, y, z))
    wp = _rotate(wp, rotation)
    return wp


def _anchor_point(wp, name):
    """World-space anchor point of a placed workplane (a named face centre, or its
    overall centre). Used to compute relational 'mate' placement."""
    if name == "center" or name not in _ANCHOR_SEL:
        c = wp.val().Center()
        return (c.x, c.y, c.z)
    f = wp.faces(_ANCHOR_SEL[name]).val().Center()
    return (f.x, f.y, f.z)


def _fold(step_list, placed):
    """Boolean-combine a list of steps' placed workplanes via their `operation`."""
    res = None
    for st in step_list:
        piece = placed.get(st.get("sequence_id"))
        if piece is None:
            continue
        op = st.get("operation", "new")
        if res is None:
            res = piece
        elif op == "join":
            res = res.union(piece, tol=1e-4)
        elif op == "cut":
            res = res.cut(piece, tol=1e-4)
        elif op == "intersect":
            res = res.intersect(piece, tol=1e-4)
        else:  # "new" later step -> add as a separate body
            res = res.add(piece)
    return res


def build_plan(plan: dict) -> dict:
    """Execute a GeometryPlan. Placement is either absolute (position/rotation) or
    relational (attach: mate this part to another so they touch by construction).
    assembly_kind decides combination: 'single_solid' folds everything into one
    connected body; 'assembly' folds within each `part` and keeps parts separate.

    Returns {ok, solid (a Workplane carrying ALL bodies), steps, failed_step?, meta}.
    """
    steps = sorted(plan.get("primitives_sequence", []), key=lambda s: s.get("sequence_id", 0))
    kind = plan.get("assembly_kind", "single_solid")
    by_id = {s.get("sequence_id"): s for s in steps}
    name_to_id = {s.get("name"): s.get("sequence_id") for s in steps if s.get("name")}
    status = []

    # 1. Build each piece (rotation applied in local frame; translation deferred).
    raw = {}
    for st in steps:
        sid = st.get("sequence_id")
        ptype = st.get("primitive_type")
        try:
            piece = _custom_solid(st.get("parameters", {})) if ptype == "custom" \
                else _primitive_solid(ptype, st.get("parameters", {}))
            piece = _as_wp(piece)
            # absolute steps get full placement now; mate steps get rotation only (mate translates later)
            if st.get("attach"):
                piece = _rotate(piece, st.get("rotation"))
            else:
                piece = _place_absolute(piece, st.get("position"), st.get("rotation"))
            raw[sid] = piece
            status.append({"sequence_id": sid, "primitive_type": ptype, "ok": True})
        except Exception as e:
            status.append({"sequence_id": sid, "primitive_type": ptype, "ok": False,
                           "error": f"{type(e).__name__}: {e}"})
            return {"ok": False, "solid": None, "steps": status, "failed_step": sid}

    # 2. Resolve placement: absolute steps are already placed; mate steps are derived
    #    from their target's resolved anchor (topological, with cycle detection).
    placed = {}
    resolving = set()

    def resolve(sid):
        if sid in placed:
            return placed[sid]
        st = by_id[sid]
        att = st.get("attach")
        if not att or att.get("to") is None:
            placed[sid] = raw[sid]          # absolute (already placed)
            return placed[sid]
        if sid in resolving:
            raise ValueError(f"attach cycle involving step {sid}")
        resolving.add(sid)
        ref = att.get("to")
        tgt_id = ref if isinstance(ref, int) and ref in by_id else name_to_id.get(ref)
        if tgt_id is None:
            try:
                tgt_id = int(ref)
            except (TypeError, ValueError):
                tgt_id = None
        if tgt_id is None or tgt_id not in by_id:
            raise ValueError(f"step {sid} attaches to unknown target {ref!r}")
        tgt = resolve(tgt_id)
        at = att.get("at", "top")
        my = att.get("my_anchor") or _OPPOSITE.get(at, "center")
        
        # Pull operation from the step to apply fuzzy boolean overlap
        operation = st.get("operation", "join")
        gap = float(att.get("gap", 0.0) or 0.0)
        
        # Auto-overlap (fuzzy boolean) to prevent coplanar face explosions
        if gap == 0.0 and operation in ("join", "cut"):
            gap = -0.1
            
        ta = _anchor_point(tgt, at)
        ma = _anchor_point(raw[sid], my)
        d = _ANCHOR_DIR.get(at, (0, 0, 0))
        target = (ta[0] + d[0] * gap, ta[1] + d[1] * gap, ta[2] + d[2] * gap)
        placed[sid] = raw[sid].translate((target[0] - ma[0], target[1] - ma[1], target[2] - ma[2]))

        
        # Apply explicit position as a relative offset if present
        if st.get("position"):
            dx, dy, dz = (list(st.get("position")) + [0, 0, 0])[:3]
            if any([dx, dy, dz]):
                placed[sid] = placed[sid].translate((dx, dy, dz))
        resolving.discard(sid)
        return placed[sid]

    try:
        for st in steps:
            resolve(st.get("sequence_id"))
    except Exception as e:
        return {"ok": False, "solid": None, "steps": status, "failed_step": None,
                "error": f"placement error: {e}"}

    # 3. Combine.
    if kind == "assembly":
        from collections import OrderedDict
        groups = OrderedDict()
        for st in steps:
            key = st.get("part") or st.get("name") or f"part_{st.get('sequence_id')}"
            groups.setdefault(key, []).append(st)
        part_solids = [r for r in (_fold(sl, placed) for sl in groups.values()) if r is not None]
        if not part_solids:
            return {"ok": False, "solid": None, "steps": status, "failed_step": None, "error": "empty plan"}
        result = part_solids[0]
        for r in part_solids[1:]:
            for v in r.vals():
                result = result.add(v)
        meta = {"assembly_kind": "assembly", "part_count": len(part_solids), "parts": list(groups.keys())}
    else:
        result = _fold(steps, placed)
        if result is None:
            return {"ok": False, "solid": None, "steps": status, "failed_step": None, "error": "empty plan"}
        meta = {"assembly_kind": "single_solid", "part_count": 1}

    # Return the WORKPLANE (carries ALL bodies) so verify/render see every part.
    return {"ok": True, "solid": result, "workplane": result, "steps": status, "meta": meta}
