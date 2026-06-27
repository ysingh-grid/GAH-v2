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


def _contour_loft_sections(sections, ruled=False):
    """GENERAL loft through N arbitrary cross-sections (technique primitive, object-agnostic).
    `sections` is a list of rows [z, x1, y1, x2, y2, ...]: the z-height of the section followed by
    its closed polygon's points. Lofts a contoured/tapered/blended solid between them (seat pan,
    bottle body, wing section, duct — any shape, not just box->box)."""
    sections = [list(map(float, row)) for row in sections]
    if len(sections) < 2:
        raise ValueError("loft_sections needs >= 2 sections")
    wp = cq.Workplane("XY")
    prev_z = 0.0
    for row in sections:
        z = row[0]
        coords = row[1:]
        if len(coords) < 6 or len(coords) % 2 != 0:
            raise ValueError("each section is [z, x1,y1, x2,y2, ...] with >= 3 points")
        pts = [(coords[i], coords[i + 1]) for i in range(0, len(coords), 2)]
        wp = wp.workplane(offset=z - prev_z).polyline(pts).close()
        prev_z = z
    return wp.loft(ruled=bool(ruled), combine=True)


def _sweep_solid_ok(out):
    """True if a swept result is a usable, non-null solid (cheap — no meshing)."""
    try:
        v = out.val() if hasattr(out, "val") else out
        return v is not None and getattr(v, "wrapped", None) is not None and not v.wrapped.IsNull()
    except Exception:
        return False


def _sweep_is_sound(out):
    """Best-effort soundness check (watertight + no self-intersections) used to PREFER a clean
    swept candidate. Lazy MeshLib bridge via verify; FAIL-OPEN (returns True/accept) if the check
    cannot run — verify_solid remains the real gate."""
    try:
        import verify as _v
    except Exception:
        try:
            from cad_kernel import verify as _v
        except Exception:
            return True
    try:
        m = _v.cq_to_meshlib(out)
        meas = _v.measure(m)
        return bool(meas["watertight"]) and int(meas["self_intersections"]) == 0
    except Exception:
        return True


def _path_has_sharp_corners(pts, tube_radius):
    """True if any interior vertex turns sharply enough that a tube of `tube_radius` would likely
    self-intersect on the bend (turn > 20 deg AND an adjacent segment shorter than ~2x the radius).
    Pure geometry — no meshing."""
    if not tube_radius or len(pts) < 3:
        return False
    r = float(tube_radius)
    for i in range(1, len(pts) - 1):
        a, b, c = pts[i - 1], pts[i], pts[i + 1]
        d1 = [b[k] - a[k] for k in range(3)]
        d2 = [c[k] - b[k] for k in range(3)]
        l1 = (sum(x * x for x in d1)) ** 0.5
        l2 = (sum(x * x for x in d2)) ** 0.5
        if l1 < 1e-9 or l2 < 1e-9:
            continue
        dot = sum(d1[k] * d2[k] for k in range(3)) / (l1 * l2)
        dot = max(-1.0, min(1.0, dot))
        turn = math.degrees(math.acos(dot))   # 0 = straight, 180 = hairpin
        if turn > 20.0 and min(l1, l2) < 2.0 * r:
            return True
    return False


def _round_path_corners(pts, iterations=2):
    """Chaikin corner-cutting on an OPEN polyline (endpoints fixed): rounds sharp corners into short
    arcs so a swept tube does not self-intersect on a tight bend (the classic swept self-intersection
    — a sharp turn whose inner offset overruns the adjacent segment for the given tube radius)."""
    p = [[float(c) for c in q] for q in pts]
    for _ in range(max(1, iterations)):
        if len(p) < 3:
            break
        out = [p[0]]
        for i in range(len(p) - 1):
            a, b = p[i], p[i + 1]
            out.append([a[k] * 0.75 + b[k] * 0.25 for k in range(3)])
            out.append([a[k] * 0.25 + b[k] * 0.75 for k in range(3)])
        out.append(p[-1])
        p = out
    return p


def _robust_sweep(section_factory, pts, tube_radius=None):
    """Sweep a section (built fresh by `section_factory` each attempt — `.sweep()` CONSUMES the
    pending wire, so it cannot be reused) along the 3D polyline `pts` ROBUSTLY.

    Self-intersection on a sharp bend is the dominant swept-geometry failure. We try a few
    constructions, FAITHFUL FIRST so an already-sound sweep is returned UNCHANGED (zero
    regression), and accept an alternative ONLY if it meshes SOUND (so an alternative can never
    make the result worse than the plain sweep):
      1. faithful path, default transition (the original construction);
      2. faithful path, ROUNDED transition (OCC corner-rounding);
      3. (only if the path bends too sharply for the radius) ONE light Chaikin corner-round, both
         transitions — note: heavy smoothing creates many short segments that WORSEN a fat tube, so
         we use a single pass and still gate on soundness.
    FAIL-OPEN: if no candidate is provably sound, return the first buildable (== the plain sweep),
    leaving verify to FAIL it and the diagnostic to tell the agent the real cause (radius too large
    for the path scale — which no corner treatment can fix; the agent must shrink the radius or
    lengthen/space the path)."""
    pts = [[float(c) for c in p] for p in pts]
    variants = [(pts, "right"), (pts, "round")]
    if tube_radius and _path_has_sharp_corners(pts, tube_radius):
        rp = _round_path_corners(pts, 1)   # ONE light pass; more iterations worsen a fat tube
        variants += [(rp, "right"), (rp, "round")]
    built = None
    for cand, trans in variants:
        try:
            sec = section_factory()
            pw = cq.Workplane("XY").polyline([tuple(p) for p in cand])
            out = sec.sweep(pw, multisection=False, transition=trans)
        except Exception:
            continue
        if not _sweep_solid_ok(out):
            continue
        if built is None:
            built = out                    # first buildable == faithful plain sweep (fail-open)
        if _sweep_is_sound(out):
            return out                     # prefer a SOUND result; faithful-first => no regression
    if built is not None:
        return built
    # absolute fail-open: the original plain sweep (its error, if any, is surfaced by build/verify)
    sec = section_factory()
    pw = cq.Workplane("XY").polyline([tuple(p) for p in pts])
    return sec.sweep(pw, multisection=False)


def swept_circle(radius, path):
    """Robust round-tube sweep of a circle of `radius` along the 3D polyline `path` — used by the
    `swept_circle` primitive template. A fresh circle section is built per attempt."""
    r = float(radius)
    pts = [[float(c) for c in p] for p in path]
    return _robust_sweep(lambda: cq.Workplane("XY").circle(r), pts, tube_radius=r)


def _contour_sweep_profile(profile, path):
    """GENERAL sweep of an arbitrary closed 2D profile along a 3D path (not just a circle).
    `profile` = list of [x,y] points (the cross-section); `path` = list of [x,y,z] points.
    Routed through the same robust sweep (soundness-preferring + fail-open)."""
    prof = [(float(p[0]), float(p[1])) for p in profile]
    pts = [[float(c) for c in p] for p in path]
    xs = [p[0] for p in prof]
    ys = [p[1] for p in prof]
    rad = 0.5 * max((max(xs) - min(xs)), (max(ys) - min(ys))) if prof else None
    return _robust_sweep(lambda: cq.Workplane("XY").polyline(prof).close(), pts, tube_radius=rad)


def _contour_revolve_profile(profile, end_fillet=0.0, angle=360.0):
    """Revolve a [radius,z] profile about the Z axis; optionally round the resulting circular
    edges by `end_fillet` mm (0 = none). Fillet is best-effort: if it fails the revolve still
    returns unfilleted (so an over-large fillet never breaks the build)."""
    prof = [(float(p[0]), float(p[1])) for p in profile]
    wp = cq.Workplane("XZ").polyline(prof).hLineTo(0).close().revolve(float(angle), (0, 0, 0), (0, 1, 0))
    if end_fillet and float(end_fillet) > 0:
        try:
            wp = wp.edges("%Circle").fillet(float(end_fillet))
        except Exception:
            pass
    return wp


def _contour_twisted_loft(profile, stations):
    """GENERAL twisted/helical loft (technique primitive, object-agnostic): loft ONE closed 2D
    profile through N stations, each [z, radius, twist_deg, scale]. At each station the profile is
    SCALED by `scale`, translated OUT to `radius` along +X (its local origin orbits the Z axis),
    and the section ROTATED `twist_deg` about Z. Builds impeller/fan/turbine blades, augers, drill
    flutes, twisted columns, mixer paddles — any profile swept with a turn. The plan supplies only
    numbers; the host owns the CadQuery (low hallucination). Same loft engine as lofted_sections, so
    an ill-posed twist surfaces through the SAME verify construction diagnostic."""
    prof = [(float(p[0]), float(p[1])) for p in profile]
    if len(prof) < 3:
        raise ValueError("twisted_loft profile needs >= 3 [x,y] points")
    sts = []
    for s in stations:
        row = (list(s) + [0.0, 0.0, 0.0, 1.0])[:4]
        sts.append((float(row[0]), float(row[1]), float(row[2]), float(row[3])))
    if len(sts) < 2:
        raise ValueError("twisted_loft needs >= 2 stations [z, radius, twist_deg, scale]")
    wp = cq.Workplane("XY")
    prev_z = 0.0
    for (z, radius, twist_deg, scale) in sts:
        sc = scale if (scale and scale > 0) else 1.0
        th = math.radians(twist_deg)
        cos_t, sin_t = math.cos(th), math.sin(th)
        pts = []
        for (x, y) in prof:
            px, py = x * sc + radius, y * sc
            pts.append((px * cos_t - py * sin_t, px * sin_t + py * cos_t))
        wp = wp.workplane(offset=z - prev_z).polyline(pts).close()
        prev_z = z
    return wp.loft(ruled=False, combine=True)


_PRIM_EVAL_NS = {
    "cq": cq, "math": math,
    "loft_sections": _contour_loft_sections,
    "sweep_profile": _contour_sweep_profile,
    "swept_circle": swept_circle,
    "revolve_profile": _contour_revolve_profile,
    "twisted_loft": _contour_twisted_loft,
}


def _primitive_solid(ptype: str, params: dict):
    """Build a primitive from its FIXED template, filling defaults for missing keys."""
    spec = _PRIMS.get(ptype)
    if not spec:
        raise ValueError(f"unknown primitive_type '{ptype}'")
    merged = {k: v.get("default") for k, v in spec.get("parameters", {}).items()}
    merged.update(params or {})
    template = spec["template"]
    expr = template.format(**merged)
    return eval(expr, dict(_PRIM_EVAL_NS))  # template is trusted (from primitives.json)


def _custom_solid(params: dict, previous_solids: dict = None):
    """Execute an LLM-authored code_sketch in an ISOLATED subprocess with a timeout,
    transferring the result as a true BREP so later boolean ops stay exact.
    Robust regardless of how the parent process was launched."""
    code = params.get("code_sketch") or params.get("code") or ""
    if not code.strip():
        raise ValueError("custom step has no code_sketch")

    # Task 5: fast, host-side API lint BEFORE the (slow) build subprocess. Catches invented methods
    # (e.g. Workplane.taper) in milliseconds with a precise correction + a KB example, instead of
    # after a full build that returns a terse traceback. High-precision (never blocks valid code).
    try:
        from cq_lint import lint_code_sketch
    except Exception:
        try:
            from cad_kernel.cq_lint import lint_code_sketch
        except Exception:
            lint_code_sketch = None
    if lint_code_sketch is not None:
        try:
            _lint = lint_code_sketch(code, params.get("cadquery_operations"))
        except Exception:
            _lint = None
        if _lint:
            raise ValueError(_lint)

    import subprocess
    runner = str(Path(__file__).resolve().parent / "_custom_runner.py")
    code_file = tempfile.mktemp(suffix=".py")
    out_brep = tempfile.mktemp(suffix=".brep")
    Path(code_file).write_text(code, encoding="utf-8")
    
    # Write previous solids to temp files
    context_file = tempfile.mktemp(suffix=".json")
    context_data = {}
    brep_files = []
    
    if previous_solids:
        from OCP.BRepTools import BRepTools
        for name, wp in previous_solids.items():
            tmp_brep = tempfile.mktemp(suffix=".brep")
            solid = wp.val() if hasattr(wp, "val") else wp
            try:
                if solid and solid.wrapped:
                    BRepTools.Write_s(solid.wrapped, tmp_brep)
                    context_data[name] = tmp_brep
                    brep_files.append(tmp_brep)
            except Exception:
                pass
                
    Path(context_file).write_text(json.dumps(context_data), encoding="utf-8")

    try:
        proc = subprocess.run([sys.executable, runner, code_file, out_brep, context_file],
                              capture_output=True, text=True, timeout=CUSTOM_TIMEOUT_S)
        if proc.returncode != 0:
            _err = proc.stderr.strip() or f"exit {proc.returncode}"
            try:
                from cq_lint import enrich_build_error
            except Exception:
                try:
                    from cad_kernel.cq_lint import enrich_build_error
                except Exception:
                    enrich_build_error = None
            if enrich_build_error is not None:
                try:
                    _err = enrich_build_error(_err, params.get("cadquery_operations"))
                except Exception:
                    pass
            raise RuntimeError("custom code_sketch failed: " + _err)
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
        for f in (code_file, out_brep, context_file) + tuple(brep_files):
            if os.path.exists(f):
                os.remove(f)


_CUSTOM_DIM_TOL = float(os.environ.get("FORGECAD_CUSTOM_DIM_TOL", "5.0"))  # gross-scale factor (unit-confusion level)


def _audit_custom_dims(piece, declared_dimensions):
    """LENIENT gross-scale guard for custom steps: a custom step can be a sound solid yet be at the
    wrong SCALE (e.g. code that builds 400mm when the model intended 40mm — a unit/scale blunder).
    If `declared_dimensions` is given, compare its values to the measured bounding-box dims
    (sorted, magnitude-only) and reject ONLY a GROSS mismatch (off by >= _CUSTOM_DIM_TOL x, default
    5x — i.e. obvious unit confusion, not a rough-estimate discrepancy). Custom is needs_review, so
    exact feature sizes are a human's job; this only catches blatant scale errors. Returns an error
    string, or None if OK / not enough info."""
    if not declared_dimensions or not isinstance(declared_dimensions, dict):
        return None
    vals = [abs(float(v)) for v in declared_dimensions.values()
            if isinstance(v, (int, float)) and float(v) > 0]
    if not vals:
        return None
    try:
        bb = piece.val().BoundingBox()
        measured = sorted([bb.xlen, bb.ylen, bb.zlen], reverse=True)
    except Exception:
        return None
    declared = sorted(vals, reverse=True)
    n = min(len(declared), len(measured))
    for d, m in zip(declared[:n], measured[:n]):
        if m <= 1e-6:
            continue
        ratio = max(d / m, m / d)
        if ratio > _CUSTOM_DIM_TOL:
            return (f"custom step scale mismatch: declared_dimensions ~{declared} but the built "
                    f"solid measures ~{[round(x,1) for x in measured]} mm (off by {ratio:.1f}x). "
                    f"Fix the code_sketch so its size matches your declared_dimensions.")
    return None


_AXIS_SEL = {"top": ">Z", "bottom": "<Z", "right": ">X", "left": "<X", "back": ">Y", "front": "<Y"}
_AXIS_DIR = {"top": (0, 0, 1), "bottom": (0, 0, -1), "right": (1, 0, 0), "left": (-1, 0, 0),
             "back": (0, 1, 0), "front": (0, -1, 0)}
_AXIS_OPP = {"top": "bottom", "bottom": "top", "left": "right", "right": "left",
             "front": "back", "back": "front"}

# Back-compatible aliases (older code / tests referenced these names).
_ANCHOR_SEL = _AXIS_SEL
_ANCHOR_DIR = {**_AXIS_DIR, "center": (0, 0, 0)}
_OPPOSITE = {**_AXIS_OPP, "center": "center"}


def _anchor_components(name):
    """Split a (possibly composite) anchor like 'top|front' into its face words."""
    if not name:
        return []
    return [p for p in str(name).split("|") if p]


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


def _rotate_vec(vec, rotation):
    """Rotate a 3-vector by [rx,ry,rz] degrees in the SAME X->Y->Z order as `_rotate` applies to a
    part (right-hand rule about each axis, through the origin). Used so an `attach.offset` is
    expressed in the part's OWN rotated frame: "slide 150 out" rotates WITH the part, which is what
    makes radial arrays (5-star bases, spokes, bolt circles) actually form a star and touch the hub
    instead of all sliding the same global direction."""
    if not rotation or not any(rotation):
        return list(vec)
    rx, ry, rz = (list(rotation) + [0, 0, 0])[:3]
    x, y, z = float(vec[0]), float(vec[1]), float(vec[2])
    if rx:
        a = math.radians(rx); c, s = math.cos(a), math.sin(a)
        y, z = y * c - z * s, y * s + z * c
    if ry:
        a = math.radians(ry); c, s = math.cos(a), math.sin(a)
        x, z = x * c + z * s, -x * s + z * c
    if rz:
        a = math.radians(rz); c, s = math.cos(a), math.sin(a)
        x, y = x * c - y * s, x * s + y * c
    return [x, y, z]


def _place_absolute(wp, position, rotation):
    """Absolute placement convention: translate (local frame) THEN rotate about the
    origin — keeps radial patterns intuitive (translate out +X, rotate about Z)."""
    if position and any(position):
        x, y, z = (list(position) + [0, 0, 0])[:3]
        wp = wp.translate((x, y, z))
    wp = _rotate(wp, rotation)
    return wp


def _anchor_point(wp, name):
    """World-space anchor point of a (possibly composite) anchor, derived from the part's
    AXIS-ALIGNED BOUNDING BOX so it is exact and FLUSH-MATING for ANY primitive and ANY rotation.
    A swept/lofted/revolved/rotated part has no reliable BREP 'top face' (the selected face's
    centroid is not the extreme), which is exactly why anchor-mating used to leave gaps and the
    agent fell back to hand-computed offsets. The bbox extreme is always well-defined:
      - 'center' / unknown            -> bbox centroid
      - one face   'top'              -> centre of that bbox face (e.g. (cx, cy, zmax))
      - two faces  'top|front'        -> midpoint of the shared bbox edge
      - three faces 'top|front|right' -> the bbox corner
    Each named face pins ITS axis to the bbox min/max (per _AXIS_DIR's sign); unpinned axes stay at
    the centroid. Falls back to BREP face/edge/vertex centres only if the bbox is unavailable."""
    comps = _anchor_components(name)
    axis_comps = [c for c in comps if c in _AXIS_DIR]
    bb = None
    try:
        bb = wp.val().BoundingBox()
    except Exception:
        bb = None
    if bb is not None:
        cx = (bb.xmin + bb.xmax) / 2.0
        cy = (bb.ymin + bb.ymax) / 2.0
        cz = (bb.zmin + bb.zmax) / 2.0
        if name == "center" or not axis_comps:
            return (cx, cy, cz)
        px, py, pz = cx, cy, cz
        for c in axis_comps:
            dx, dy, dz = _AXIS_DIR[c]
            if dx > 0:
                px = bb.xmax
            elif dx < 0:
                px = bb.xmin
            if dy > 0:
                py = bb.ymax
            elif dy < 0:
                py = bb.ymin
            if dz > 0:
                pz = bb.zmax
            elif dz < 0:
                pz = bb.zmin
        return (px, py, pz)
    # --- BREP fallback (only if the bbox is unavailable) ---
    if name == "center" or not axis_comps:
        c = wp.val().Center()
        return (c.x, c.y, c.z)
    sel = " and ".join(_AXIS_SEL[c] for c in axis_comps)
    if len(axis_comps) == 1:
        objs = wp.faces(sel).vals()
    elif len(axis_comps) == 2:
        objs = wp.edges(sel).vals()
    else:
        objs = wp.vertices(sel).vals()
    if not objs:
        raise ValueError(
            f"anchor {name!r} matched no geometry on this part — its shape may not have "
            f"that face/edge/corner. Use a face anchor (top/bottom/left/right/front/back) "
            f"or check the part's orientation.")
    cs = [o.Center() for o in objs]
    n = len(cs)
    return (sum(c.x for c in cs) / n, sum(c.y for c in cs) / n, sum(c.z for c in cs) / n)


def _anchor_dir(name):
    """Outward direction for the gap offset: the normalised sum of the component face
    normals. Single face -> its normal; edge/corner -> the diagonal away from the body."""
    comps = [c for c in _anchor_components(name) if c in _AXIS_DIR]
    if not comps:
        return (0.0, 0.0, 0.0)
    vx = sum(_AXIS_DIR[c][0] for c in comps)
    vy = sum(_AXIS_DIR[c][1] for c in comps)
    vz = sum(_AXIS_DIR[c][2] for c in comps)
    mag = (vx * vx + vy * vy + vz * vz) ** 0.5
    return (0.0, 0.0, 0.0) if mag == 0 else (vx / mag, vy / mag, vz / mag)


def _opposite_anchor(name):
    """Default my_anchor: component-wise opposite of `at` ('top|front' -> 'bottom|back')."""
    comps = _anchor_components(name)
    opp = [_AXIS_OPP.get(c, c) for c in comps]
    return "|".join(opp) if opp else "center"


class GeometryCombineError(ValueError):
    """C2 — a genuine, DESIGN-LEVEL boolean-combine failure (never a raw OCC 'Null TopoDS_Shape').
    Raised only after the host healed both shapes and retried with escalating fuzzy tolerances."""
    def __init__(self, op, detail):
        self.op = op
        self.detail = detail
        super().__init__(
            f"could not {op} two parts ({detail}). The kernel healed both shapes and retried with "
            f"fuzzy tolerance, but the boolean still failed — the geometry is likely too thin, "
            f"tangent, or self-intersecting to FUSE. FIX (design-level, not a retry): for a "
            f"multi-part object make each rigid piece its OWN part (operation 'new') and connect "
            f"them with `attach` so they TOUCH — an assembly needs NO boolean fuse and cannot hit "
            f"this. Reserve join/cut for a single monolithic body, and give parts a clear overlap.")


def _heal(wp):
    """Best-effort clean/heal of a solid (remove degenerate faces, fix tolerances) so a subsequent
    boolean is more likely to succeed. Never raises."""
    try:
        return wp.clean()
    except Exception:
        return wp


def _solid_volume(obj):
    """Volume (mm^3) of a Workplane/Shape, summed over all solids it carries; None if it cannot be
    measured (so callers can FAIL-OPEN rather than reject a legitimate operand)."""
    try:
        if obj is None:
            return None
        if hasattr(obj, "vals"):
            tot = 0.0
            got = False
            for v in obj.vals():
                try:
                    tot += float(v.Volume())
                    got = True
                except Exception:
                    continue
            return tot if got else None
        return float(obj.Volume())
    except Exception:
        return None


def _combined_ok(out, method, vol_a=None, vol_b=None):
    """True if a boolean result is a usable solid. For a UNION this is now VOLUME-MONOTONIC: a real
    union can never be SMALLER than either operand, so a result that shrank below max(vol_a, vol_b)
    means a body was silently DROPPED (the impeller bug: hub+blade -> blade only) and is REJECTED.
    Cut/intersect stay 'any non-null result is acceptable' (they legitimately shrink). FAIL-OPEN:
    if a volume cannot be measured we do NOT reject on that basis (preserves prior behaviour)."""
    try:
        v = out.val() if hasattr(out, "val") else out
        if v is None or getattr(v, "wrapped", None) is None or v.wrapped.IsNull():
            return False
        if method == "union":
            ov = _solid_volume(out)
            if ov is None:
                return True                      # cannot measure -> accept (legacy behaviour)
            if ov <= 1e-9:
                return False
            if vol_a is not None and vol_b is not None:
                need = max(vol_a, vol_b)
                tol = max(1e-6, 1e-3 * need)     # 0.1% relative + tiny absolute (heal/fuzzy jitter)
                if ov < need - tol:
                    return False                 # a body was dropped — reject, force a better attempt
            return True
        return True  # cut/intersect: a non-null result is acceptable
    except Exception:
        return False


_BOOL_METHOD = {"join": "union", "cut": "cut", "intersect": "intersect"}
# Shape-level (OCC BREP) counterparts — used as the robust escalation when the Workplane-level
# boolean silently drops an operand. cq.Shape.fuse/cut/intersect operate directly on the solids.
_SHAPE_METHOD = {"join": "fuse", "cut": "cut", "intersect": "intersect"}


def _shape_boolean(res, piece, op):
    """SHAPE-LEVEL boolean on the underlying solids (bypasses the Workplane stack, which is what
    silently drops the larger operand on a fragile union). Returns a Workplane wrapping the result,
    or None if it cannot be built. Never raises."""
    try:
        sa = res.val() if hasattr(res, "val") else res
        sb = piece.val() if hasattr(piece, "val") else piece
        if sa is None or sb is None:
            return None
        shp = getattr(sa, _SHAPE_METHOD[op])(sb)
        if shp is None or getattr(shp, "wrapped", None) is None or shp.wrapped.IsNull():
            return None
        return cq.Workplane("XY").add(shp)
    except Exception:
        return None


def _robust_boolean(res, piece, op):
    """C1 — ONE robust combine for ALL geometry (primitive OR custom). Try a tight boolean, then
    HEAL both inputs and RETRY with escalating FUZZY tolerances, VALIDATING each result is
    volume-monotonic (a union must keep both bodies). If every Workplane-level attempt drops a body
    or nulls, ESCALATE to a shape-level fuse on the raw solids. Only if THAT also fails do we raise
    a structured, design-level GeometryCombineError — never a raw OCC null and never a silently
    dropped body. A non-boolean ('new') just adds the body. Protects every fuse in the kernel."""
    method = _BOOL_METHOD.get(op)
    if method is None:
        return res.add(piece)
    vol_a = _solid_volume(res)
    vol_b = _solid_volume(piece)
    last = "unknown error"
    for tol, heal in ((1e-4, False), (1e-3, True), (0.1, True), (0.5, True)):
        a = _heal(res) if heal else res
        b = _heal(piece) if heal else piece
        try:
            out = getattr(a, method)(b, tol=tol)
            if _combined_ok(out, method, vol_a, vol_b):
                return out
            last = ("boolean dropped a body (result smaller than its largest input)"
                    if op == "join" else "boolean produced a null/empty solid")
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
    # Escalation: shape-level boolean on the raw solids (robust against Workplane-stack body-drops).
    shaped = _shape_boolean(res, piece, op)
    if shaped is not None and _combined_ok(shaped, method, vol_a, vol_b):
        return shaped
    if shaped is not None and op == "join":
        last = "shape-level fuse still dropped a body (tangent/coincident faces)"
    raise GeometryCombineError(op, last)


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
        elif op in ("join", "cut", "intersect"):
            res = _robust_boolean(res, piece, op)
        else:  # "new" later step -> add as a separate body
            res = res.add(piece)
    return res


def _pattern_copies(piece, pat):
    """Return [base, copy1, ...] for a pattern applied to an already-placed piece.
    linear: copy i translated by i*step. radial: copy i rotated i*angle about an axis
    line through `center`. Fully general (any count/axis/spacing/centre) and exact —
    the kernel does the trig so the planner never hand-computes orbit coordinates."""
    kind = (pat.get("kind") or "").lower()
    count = int(pat.get("count", 1))
    if count < 1:
        return [piece]
    out = [piece]
    if kind == "linear":
        step = (list(pat.get("step") or [0, 0, 0]) + [0, 0, 0])[:3]
        for i in range(1, count):
            out.append(piece.translate((step[0] * i, step[1] * i, step[2] * i)))
    elif kind == "radial":
        axis = (pat.get("axis") or "z").lower()
        center = (list(pat.get("center") or [0, 0, 0]) + [0, 0, 0])[:3]
        sweep = float(pat.get("sweep_deg", 360.0))
        if count > 1:
            ang = sweep / count if abs(abs(sweep) - 360.0) < 1e-9 else sweep / (count - 1)
        else:
            ang = 0.0
        a = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}.get(axis, (0, 0, 1))
        start = tuple(center)
        end = (center[0] + a[0], center[1] + a[1], center[2] + a[2])
        for i in range(1, count):
            out.append(piece.rotate(start, end, ang * i))
    else:
        raise ValueError(f"unknown pattern kind {kind!r} (use 'linear' or 'radial')")
    return out


def _expand_placed(step_list, placed):
    """Expand patterned steps into multiple (operation, piece) entries; plain steps pass
    through unchanged; MODIFIER steps emit a marker so _fold_seq can refine the running result
    in place at the right sequence position. Combined later by _fold_seq."""
    seq = []
    for st in step_list:
        if st.get("primitive_type") in MODIFIERS:
            seq.append(("__modifier__", st))
            continue
        piece = placed.get(st.get("sequence_id"))
        if piece is None:
            continue
        op = st.get("operation", "new")
        pat = st.get("pattern")
        if not pat:
            seq.append((op, piece))
        else:
            for c in _pattern_copies(piece, pat):
                seq.append((op, c))
    return seq


# ---- Modifier verbs (round / bevel / hollow the running solid) -------------------------
MODIFIERS = {"fillet", "chamfer", "shell"}
_EDGE_SEL = {"all": None, "vertical": "|Z", "top": ">Z", "bottom": "<Z"}
_FACE_SEL = {"top": ">Z", "bottom": "<Z", "left": "<X", "right": ">X", "front": "<Y", "back": ">Y"}


def _apply_modifier(solid, step):
    """Apply a fillet/chamfer/shell to the already-built running solid. Host owns the CadQuery
    wiring; the plan supplies only numbers + an edge/face keyword. Raises an actionable error if
    there is no prior solid, or the operation fails (e.g. radius too large)."""
    mt = step.get("primitive_type")
    sid = step.get("sequence_id")
    if solid is None:
        raise ValueError(
            f"modifier '{mt}' at step {sid} has no prior solid to refine — place it AFTER the "
            f"step(s) that build the body it should round/bevel/hollow.")
    p = step.get("parameters", {}) or {}
    wp = _as_wp(solid)
    if mt == "fillet":
        sel = _EDGE_SEL.get(p.get("edges", "all"))
        edges = wp.edges() if sel is None else wp.edges(sel)
        return edges.fillet(float(p["radius"]))
    if mt == "chamfer":
        sel = _EDGE_SEL.get(p.get("edges", "all"))
        edges = wp.edges() if sel is None else wp.edges(sel)
        return edges.chamfer(float(p["distance"]))
    if mt == "shell":
        face = _FACE_SEL.get(p.get("face", "top"), ">Z")
        return wp.faces(face).shell(-abs(float(p["thickness"])))
    raise ValueError(f"unknown modifier '{mt}' at step {sid}")


def _fold_seq(seq):
    """Boolean-combine an ordered list of (operation, piece); '__modifier__' entries refine the
    running result in place."""
    res = None
    for op, piece in seq:
        if op == "__modifier__":
            res = _apply_modifier(res, piece)
            continue
        if res is None:
            res = piece
        elif op in ("join", "cut", "intersect"):
            res = _robust_boolean(res, piece, op)
        else:
            res = res.add(piece)
    return res


def _fusion_audit(steps, placed, raw):
    """Conservative invariant data for a single_solid, so verify can catch a SILENTLY DROPPED body
    (the impeller bug) deterministically. A union/join can only ADD volume; cuts remove at most the
    cut piece's whole volume. So the final solid must satisfy:
        final_volume >= max(additive body volume) - sum(cut piece volume)   [a conservative floor]
    We compute that floor here. The check is NOT applicable (and is skipped, fail-open) if the
    sequence uses `intersect` or any MODIFIER (shell/fillet/chamfer can shrink volume arbitrarily),
    or if any operand volume cannot be measured — so it never false-fails a legitimate build."""
    try:
        additive = []          # (name, volume) for new/join bodies
        total_cut = 0.0
        applicable = True
        for st in steps:
            pt = st.get("primitive_type")
            op = st.get("operation", "new")
            if pt in MODIFIERS or op == "intersect":
                applicable = False
                continue
            sid = st.get("sequence_id")
            pc = placed.get(sid)
            if pc is None:
                pc = raw.get(sid)
            vv = _solid_volume(pc) if pc is not None else None
            if vv is None:
                applicable = False
                continue
            if op == "cut":
                total_cut += vv
            else:                                  # new / join -> additive body
                additive.append((st.get("name") or f"step_{sid}", vv))
        if not additive:
            applicable = False
        max_name, max_vol = (None, None)
        if additive:
            max_name, max_vol = max(additive, key=lambda kv: kv[1])
        return {"applicable": bool(applicable),
                "max_additive_volume": max_vol,
                "total_cut_volume": total_cut,
                "largest_additive_name": max_name}
    except Exception:
        return {"applicable": False, "max_additive_volume": None,
                "total_cut_volume": 0.0, "largest_additive_name": None}


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
    # Map each PART group name -> its member step ids, so `attach.to` can name a whole part (the
    # agent reasons in parts; a part may be several steps, e.g. backrest = outer + spine).
    part_members = {}
    for s in steps:
        pkey = s.get("part")
        if pkey:
            part_members.setdefault(pkey, []).append(s.get("sequence_id"))
    status = []

    # 1. Build each piece (rotation applied in local frame; translation deferred).
    raw = {}
    name_to_raw = {}
    for st in steps:
        sid = st.get("sequence_id")
        name = st.get("name")
        ptype = st.get("primitive_type")
        if ptype in MODIFIERS:
            # Modifiers (fillet/chamfer/shell) build no standalone solid and have no placement;
            # they refine the running result during the fold (handled in _expand_placed/_fold_seq).
            status.append({"sequence_id": sid, "primitive_type": ptype, "ok": True})
            continue
        try:
            piece = _custom_solid(st.get("parameters", {}), previous_solids=name_to_raw) if ptype == "custom" \
                else _primitive_solid(ptype, st.get("parameters", {}))
            piece = _as_wp(piece)
            if ptype == "custom":
                _dim_err = _audit_custom_dims(piece, (st.get("parameters", {}) or {}).get("declared_dimensions"))
                if _dim_err:
                    raise ValueError(_dim_err)
            # absolute steps get full placement now; mate steps get rotation only (mate translates later)
            if st.get("attach"):
                piece = _rotate(piece, st.get("rotation"))
            else:
                piece = _place_absolute(piece, st.get("position"), st.get("rotation"))
            raw[sid] = piece
            if name:
                name_to_raw[name] = piece
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
        if st.get("primitive_type") in MODIFIERS:
            return None                     # modifiers are not placed; applied during the fold
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
        if tgt_id is not None and tgt_id in by_id:
            tgt = resolve(tgt_id)                       # attach to a STEP (name/id) — keeps priority
        elif isinstance(ref, str) and ref in part_members:
            # attach to a PART GROUP: anchor against the COMBINED geometry of its resolved member
            # steps (so `attach.to:"backrest"` works even though the backrest is several steps).
            member_solids = []
            for m in part_members[ref]:
                if m == sid or by_id.get(m, {}).get("primitive_type") in MODIFIERS:
                    continue
                rm = resolve(m)
                if rm is not None:
                    member_solids.append(rm)
            if not member_solids:
                raise ValueError(f"step {sid} attaches to part {ref!r} but it has no resolvable members")
            tgt = cq.Workplane("XY")                    # combined view -> bbox anchor spans the part
            for rm in member_solids:
                for v in rm.vals():
                    tgt = tgt.add(v)
        else:
            raise ValueError(f"step {sid} attaches to unknown target {ref!r}")
        at = att.get("at", "top")
        my = att.get("my_anchor") or _opposite_anchor(at)

        # Pull operation from the step to apply fuzzy boolean overlap
        operation = st.get("operation", "join")
        gap = float(att.get("gap", 0.0) or 0.0)

        # Auto-overlap (fuzzy boolean) to prevent coplanar face explosions
        if gap == 0.0 and operation in ("join", "cut"):
            gap = -0.1

        ta = _anchor_point(tgt, at)
        ma = _anchor_point(raw[sid], my)
        d = _anchor_dir(at)
        target = (ta[0] + d[0] * gap, ta[1] + d[1] * gap, ta[2] + d[2] * gap)
        placed[sid] = raw[sid].translate((target[0] - ma[0], target[1] - ma[1], target[2] - ma[2]))

        # Relative slide AFTER the mate. Both legacy `position` and `attach.offset` are honoured,
        # additively. CRITICAL: the slide is PROJECTED ONTO THE MATING PLANE — its component along
        # the mate normal is removed — so it can only slide the part ACROSS the contact face, never
        # lift it off the mate. This keeps `attach`'s promise ("parts touch") unbreakable; for
        # intentional spacing along the normal, use `gap` (the dedicated, contact-aware field).
        slide = [0.0, 0.0, 0.0]
        if st.get("position"):
            for i, v in enumerate((list(st.get("position")) + [0, 0, 0])[:3]):
                slide[i] += v
        if att.get("offset"):
            for i, v in enumerate((list(att.get("offset")) + [0, 0, 0])[:3]):
                slide[i] += v
        if any(slide):
            # Task 7 — COHERENT FRAME: express the slide in the part's OWN (rotated) frame, so an
            # offset rotates WITH the part. Previously the slide was applied in the GLOBAL frame, so
            # five radial legs each rotated by k*72 deg but offset [150,0,0] all shoved +150 in
            # global X — clumping instead of forming a star, and not touching the hub. Rotating the
            # slide by the step's rotation makes the model's spatial intent ("out along this part")
            # render faithfully for ANY arrangement (5-star bases, spokes, fan blades, bolt circles).
            slide = _rotate_vec(slide, st.get("rotation"))
            nrm = _anchor_dir(at)  # outward mate normal (unit) or (0,0,0)
            if any(nrm):
                # Still PROJECT OUT the component along the mate normal, so the slide can only move
                # the part ACROSS the contact face — never lift it off the mate (contact preserved).
                dot = slide[0] * nrm[0] + slide[1] * nrm[1] + slide[2] * nrm[2]
                slide = [slide[i] - dot * nrm[i] for i in range(3)]
            if any(abs(s) > 1e-9 for s in slide):
                placed[sid] = placed[sid].translate(tuple(slide))
        resolving.discard(sid)
        return placed[sid]

    try:
        for st in steps:
            resolve(st.get("sequence_id"))
    except Exception as e:
        return {"ok": False, "solid": None, "steps": status, "failed_step": None,
                "error": f"placement error: {e}"}

    # 3. Combine. Patterned steps expand HERE: one step contributes `count` placed copies,
    #    all combined with that step's operation (so a radial/linear feature array is exact).
    if kind == "assembly":
        from collections import OrderedDict
        groups = OrderedDict()
        for st in steps:
            key = st.get("part") or st.get("name") or f"part_{st.get('sequence_id')}"
            groups.setdefault(key, []).append(st)
        part_solid_map = OrderedDict()
        try:
            for key, sl in groups.items():
                r = _fold_seq(_expand_placed(sl, placed))
                if r is not None:
                    part_solid_map[key] = r
        except Exception as e:
            return {"ok": False, "solid": None, "steps": status, "failed_step": None,
                    "error": f"modifier/combine error: {type(e).__name__}: {e}"}
        # Fix A: enforce the attach contact guarantee on this assembly (intent-only, fail-open).
        # A part that DECLARED attach.to a different part but drifted off its mate is snapped back
        # into contact with that target, so a fully-attached design can't be left undeliverable by
        # an imperfect offset. Absolute-position parts are never moved (signal preserved).
        snap_info = []
        if len(part_solid_map) > 1:
            try:
                import verify as _verify
            except Exception:
                try:
                    from cad_kernel import verify as _verify
                except Exception:
                    _verify = None
            if _verify is not None:
                step_to_group = {}
                for gkey, sl in groups.items():
                    for st in sl:
                        if st.get("name"):
                            step_to_group[st.get("name")] = gkey
                        step_to_group[st.get("sequence_id")] = gkey
                    step_to_group.setdefault(gkey, gkey)   # attach.to may name the PART GROUP itself
                group_targets = {}
                for gkey, sl in groups.items():
                    for st in sl:
                        att = st.get("attach")
                        if att and att.get("to") is not None and float(att.get("gap", 0) or 0) <= 0.5:
                            ref = att.get("to")
                            tg = step_to_group.get(ref)
                            if tg is None:
                                try:
                                    tg = step_to_group.get(int(ref))
                                except (TypeError, ValueError):
                                    tg = None
                            if tg and tg != gkey:
                                group_targets[gkey] = tg
                                break
                try:
                    part_solid_map, snap_info = _verify.snap_assembly_to_contact(part_solid_map, group_targets)
                except Exception:
                    snap_info = []
        part_solids = list(part_solid_map.values())
        if not part_solids:
            return {"ok": False, "solid": None, "steps": status, "failed_step": None, "error": "empty plan"}
        # Build the combined view from a FRESH workplane — do NOT seed from part_solids[0],
        # because .add mutates it in place and would pollute part_solid_map['<first part>']
        # with every other part's bodies (breaking per-part coherence measurement).
        result = cq.Workplane("XY")
        for r in part_solids:
            for v in r.vals():
                result = result.add(v)
        # part_solids exposed so the verifier can check assembly COHERENCE (each part sound +
        # the parts form ONE connected, contact-touching object) rather than a raw blob count.
        meta = {"assembly_kind": "assembly", "part_count": len(part_solids),
                "parts": list(groups.keys()), "part_solids": part_solid_map, "snapped": snap_info}
    else:
        try:
            result = _fold_seq(_expand_placed(steps, placed))
        except Exception as e:
            return {"ok": False, "solid": None, "steps": status, "failed_step": None,
                    "error": f"modifier/combine error: {type(e).__name__}: {e}"}
        if result is None:
            return {"ok": False, "solid": None, "steps": status, "failed_step": None, "error": "empty plan"}
        meta = {"assembly_kind": "single_solid", "part_count": 1,
                "fusion_audit": _fusion_audit(steps, placed, raw)}

    # Return the WORKPLANE (carries ALL bodies) so verify/render see every part.
    return {"ok": True, "solid": result, "workplane": result, "steps": status, "meta": meta}
