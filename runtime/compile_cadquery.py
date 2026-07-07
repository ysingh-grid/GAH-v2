"""Compile a PrimitivePlan into a runnable CadQuery script (the canonical target).

This is the *deterministic* half of the dual-compiler pair (the forge.js half
lives in `runtime/compile_forge.py`). It fills each library primitive's
CadQuery `template` with the step's parameters, places it (rotate-about-origin
then translate), optionally replicates it (polar / linear pattern), and folds
the steps together with CSG booleans into a single `result` solid that
`tools/execute_cadquery.py` knows how to run.

The compiler is pure: it returns a code string and never touches disk or runs
CadQuery itself. A malformed plan (missing primitive/template, unsupported
operation) raises `CompileError`, which the loop routes back to the RLM tagged
as a `cadquery_compile` failure.
"""

from __future__ import annotations

from typing import Any

from runtime.schema import FinishOp, FinishStep, Operation, Pattern, PatternType, PrimitivePlan, PrimitiveStep

# Helpers injected once at the top of every generated script. Keeping them in
# the generated code (rather than emitting inline copies per step) keeps the
# output readable and each step's code a single expression.
_PREAMBLE = '''import cadquery as cq


def _place(solid, position, orientation):
    """Rotate about the origin (X, then Y, then Z degrees) then translate."""
    rx, ry, rz = orientation
    solid = (
        solid.rotate((0, 0, 0), (1, 0, 0), rx)
        .rotate((0, 0, 0), (0, 1, 0), ry)
        .rotate((0, 0, 0), (0, 0, 1), rz)
    )
    return solid.translate(position)


def _polar(solid, count, axis, angle_deg):
    """Union `count` copies orbited about `axis` (through origin), evenly spread."""
    out = None
    for k in range(count):
        copy = solid.rotate((0, 0, 0), axis, k * (angle_deg / count))
        out = copy if out is None else out.union(copy)
    return out


def _linear(solid, count, spacing):
    """Union `count` copies, each offset from the previous by `spacing`."""
    sx, sy, sz = spacing
    out = None
    for k in range(count):
        copy = solid.translate((sx * k, sy * k, sz * k))
        out = copy if out is None else out.union(copy)
    return out


def _loft(profile, heights, rotations, ruled=False):
    """Blend one profile through N stations stacked along Z, each rotated.

    `heights[i]`/`rotations[i]` pair up: station i sits at Z=heights[i],
    with `profile` pre-rotated rotations[i] degrees about Z before blending.
    Stacking stations with increasing rotation is how a continuously twisted
    blade/vane is built — a plain extrude (no twist) and revolve (axisymmetric
    only) cannot express that. (Flat parallel lists rather than a list of
    per-station dicts because PrimitiveStep.parameters — runtime/schema.py
    ParamValue — only accepts scalars/flat-lists/2D-lists, not nested objects.)
    """
    pts = [tuple(p) for p in profile]
    sketches = []
    for z, rot in zip(heights, rotations):
        sk = cq.Sketch().polygon(pts)
        sk = sk.moved(cq.Location(z=z, rz=rot))
        sketches.append(sk)
    return cq.Workplane().placeSketch(*sketches).loft(ruled=ruled)


def _path_wire_and_plane(path):
    """Spline wire through GLOBAL [x,y,z] points + the start plane for a profile.

    Built via Edge.makeSpline on raw Vectors, NOT Workplane("XZ").spline(tuples)
    — the latter interprets 3-tuples in the workplane's LOCAL frame (with an
    axis-swapped, sign-flipped 3rd component), silently producing a bend in the
    wrong place for input that looks like plain global XYZ. The returned plane
    sits at the path's first point with its normal along the path's initial
    tangent: a profile drawn on any OTHER plane is not perpendicular to the
    path and the sweep silently produces a skewed solid with collapsed volume
    (measured: a sharp bend swept from a flat XY profile lost >50% volume while
    still reporting isValid()=True and a correct-looking bbox).
    """
    edge = cq.Edge.makeSpline([cq.Vector(*p) for p in path])
    wire = cq.Wire.assembleEdges([edge])
    plane = cq.Plane(origin=cq.Vector(*path[0]), normal=edge.tangentAt(0))
    return wire, plane


def _sweep(profile, path, multisection=False):
    """Sweep a 2D profile along a 3D path (spline through `path`'s points).

    `path` is a list of [x,y,z] GLOBAL points; the profile is drawn on a plane
    perpendicular to the path's start (see _path_wire_and_plane for why).
    isFrenet keeps the section oriented to the path as it bends. Complements
    _loft: sweep varies POSITION along a path with a fixed profile, loft
    varies PROFILE/rotation across fixed Z stations.
    """
    path_wire, plane = _path_wire_and_plane(path)
    return (
        cq.Workplane(plane)
        .polyline([tuple(p) for p in profile])
        .close()
        .sweep(path_wire, multisection=multisection, isFrenet=True)
    )


def _tube(radius, wall, path):
    """Hollow circular tube along a 3D path: pipes, elbows, ducts, conduits.

    Sweeps the outer and inner circles SEPARATELY along the same path, then
    cuts — sweeping a pre-cut annular profile is the documented-degenerate
    idiom (see KB "Swept Hollow Pipe Elbow"). wall must be < radius.
    """
    path_wire, plane = _path_wire_and_plane(path)
    outer = cq.Workplane(plane).circle(radius).sweep(path_wire, isFrenet=True)
    inner = cq.Workplane(plane).circle(radius - wall).sweep(path_wire, isFrenet=True)
    return outer.cut(inner)


def _helix_sweep(coil_radius, pitch, height, wire_radius):
    """Circular wire swept along a helix: springs, coils, thread-like features.

    The helix rises along +Z from the origin; the section is drawn at the
    helix's start point (coil_radius, 0, 0) facing the winding direction.
    """
    helix = cq.Wire.makeHelix(pitch=pitch, height=height, radius=coil_radius)
    return (
        cq.Workplane("XZ", origin=(coil_radius, 0, 0))
        .circle(wire_radius)
        .sweep(cq.Workplane(obj=helix), isFrenet=True)
    )


def _loft_between(profile_bottom, profile_top, height, rotation_deg=0.0):
    """Loft between two DIFFERENT profiles: funnels, adapters, transitions.

    profile_bottom sits at Z=0, profile_top at Z=height (optionally rotated
    about Z by rotation_deg). Distinct from _loft, which blends ONE profile
    through many rotated stations — two DIFFERENT profiles can't be expressed
    there because ParamValue caps nesting at a 2D list (a list of N profiles
    would be 3 deep), so exactly-two named profile params is the schema-legal
    encoding of shape-to-shape transitions.
    """
    sk1 = cq.Sketch().polygon([tuple(p) for p in profile_bottom])
    sk2 = cq.Sketch().polygon([tuple(p) for p in profile_top])
    sk2 = sk2.moved(cq.Location(z=height, rz=rotation_deg))
    return cq.Workplane().placeSketch(sk1, sk2).loft()
'''


class CompileError(Exception):
    """Raised when a plan cannot be turned into CadQuery code (bad plan / library)."""


def _fill_template(spec: dict[str, Any], params: dict[str, Any]) -> str:
    """Fill a primitive's CadQuery template with params merged over its defaults."""
    known = spec.get("parameters", {})
    effective = {name: meta.get("default") for name, meta in known.items()}
    effective.update(params)
    template = spec.get("template")
    if not template:
        raise CompileError(f"primitive '{spec.get('name')}' has no CadQuery template")
    try:
        filled: str = template.format(**effective)
        return filled
    except KeyError as exc:
        raise CompileError(
            f"template for '{spec.get('name')}' needs parameter {exc} which was not provided"
        ) from exc


def _pattern_expr(var: str, pattern: Pattern) -> str:
    """Return the code expression that replicates `var` per the pattern."""
    if pattern.type is PatternType.polar:
        return f"_polar({var}, {pattern.count}, {tuple(pattern.axis)}, {pattern.angle_deg})"
    return f"_linear({var}, {pattern.count}, {tuple(pattern.spacing)})"


def _step_lines(step: PrimitiveStep, spec: dict[str, Any], index: int) -> list[str]:
    """Emit the code lines that build, place, and (optionally) pattern one step."""
    var = f"s{index}"
    lines = [
        f"# step '{step.id}' — {step.operation.value} {step.primitive}",
        f"{var} = {_fill_template(spec, step.parameters)}",
        f"{var} = _place({var}, {tuple(step.position)}, {tuple(step.orientation)})",
    ]
    if step.pattern is not None:
        lines.append(f"{var} = {_pattern_expr(var, step.pattern)}")
    return lines


def _accumulate_line(step: PrimitiveStep, index: int) -> str:
    """Emit the CSG fold line that merges step `index` into `result`."""
    var = f"s{index}"
    if step.operation is Operation.base:
        return f"result = {var}"
    if step.operation is Operation.union:
        return f"result = result.union({var})"
    if step.operation is Operation.cut:
        return f"result = result.cut({var})"
    if step.operation is Operation.intersect:
        return f"result = result.intersect({var})"
    raise CompileError(
        f"operation '{step.operation.value}' (step '{step.id}') is not a CSG fold "
        f"(base/union/cut/intersect). Post-body modifiers (fillet/chamfer/shell/holes/"
        f"mirror) must be FinishStep entries, not PrimitiveStep operations."
    )

def _compile_finish_step_cq(step: FinishStep) -> list[str]:
    """Emit CadQuery code lines that apply a FinishStep to `result`.

    Each op modifies the already-accumulated `result` solid in place.
    Fillet/chamfer are NOT wrapped in try/except: OCCT raises StdFail_NotDone
    when the radius/chamfer is too large for the geometry, and letting that
    propagate is deliberate — tools/execute_cadquery.py's own exec() wrapper
    already catches any unhandled exception and returns success=False with the
    traceback, which runtime/loop.py routes as a `cadquery_execute` failure
    straight into replan_with_feedback. A silent skip previously produced a
    "successful" part missing the requested fillet with no signal anything was
    wrong — replanning with a smaller/valid radius is the correct behavior.
    """
    lines = [f"# finish '{step.id}' — {step.op.value}"]

    if step.op is FinishOp.fillet:
        sel = step.selector or "|Z"
        lines.append(f"result = result.edges({sel!r}).fillet({float(step.value)})")

    elif step.op is FinishOp.chamfer:
        sel = step.selector or "|Z"
        lines.append(f"result = result.edges({sel!r}).chamfer({float(step.value)})")

    elif step.op is FinishOp.shell:
        face_sel = step.selector or ">Z"
        thickness = -abs(float(step.value))  # negative = inward (preserve outer dims)
        lines.append(f"result = result.faces({face_sel!r}).shell({thickness})")

    elif step.op is FinishOp.hole:
        face_sel = step.face or ">Z"
        diameter = float(step.value)
        if step.positions:
            pts = list(step.positions)  # [(x, y), ...]
            lines.append(
                f"result = result.faces({face_sel!r}).workplane()"
                f".pushPoints({pts}).hole({diameter})"
            )
        else:
            lines.append(
                f"result = result.faces({face_sel!r}).workplane().hole({diameter})"
            )

    elif step.op is FinishOp.cbore:
        # value = [clr_dia, bore_dia, bore_depth]
        v = list(step.value) if isinstance(step.value, list) else [step.value, step.value * 1.5, 3.0]
        clr_d, bore_d, bore_dep = float(v[0]), float(v[1]), float(v[2])
        face_sel = step.face or ">Z"
        if step.positions:
            pts = list(step.positions)
            lines.append(
                f"result = result.faces({face_sel!r}).workplane()"
                f".pushPoints({pts}).cboreHole({clr_d}, {bore_d}, {bore_dep})"
            )
        else:
            lines.append(
                f"result = result.faces({face_sel!r}).workplane()"
                f".cboreHole({clr_d}, {bore_d}, {bore_dep})"
            )

    elif step.op is FinishOp.csk:
        # value = [clr_dia, csk_dia, csk_angle_deg]
        v = list(step.value) if isinstance(step.value, list) else [step.value, step.value * 1.8, 82.0]
        clr_d, csk_d, angle = float(v[0]), float(v[1]), float(v[2])
        face_sel = step.face or ">Z"
        if step.positions:
            pts = list(step.positions)
            lines.append(
                f"result = result.faces({face_sel!r}).workplane()"
                f".pushPoints({pts}).cskHole({clr_d}, {csk_d}, {angle})"
            )
        else:
            lines.append(
                f"result = result.faces({face_sel!r}).workplane()"
                f".cskHole({clr_d}, {csk_d}, {angle})"
            )

    elif step.op is FinishOp.mirror:
        # selector holds the mirror plane ("XY"/"XZ"/"YZ"); union the reflection
        # back onto the body to build a symmetric part from one designed half.
        plane = step.selector or "XZ"
        lines.append(f"result = result.union(result.mirror({plane!r}))")

    else:
        # Every FinishOp MUST emit a real operation. An unhandled op (e.g. a new
        # enum value added without a compiler branch) would otherwise return only
        # the comment line above — a silent no-op that leaves the step "in the
        # plan but not applied" with a falsely-successful execution. Fail loudly
        # instead so the loop routes it to the replanner, matching how
        # _accumulate_line rejects an unknown PrimitiveStep operation.
        raise CompileError(
            f"finish step '{step.id}': op '{step.op.value}' has no compiler branch "
            f"— it would be silently skipped. Add a branch in _compile_finish_step_cq."
        )

    return lines


def compile_plan_to_cadquery(plan: PrimitivePlan, library: dict[str, Any]) -> str:
    """Compile a PrimitivePlan into a CadQuery script that assigns `result`.

    Args:
        plan: A structurally-valid PrimitivePlan.
        library: The primitives library dict (name -> spec) from
            `runtime.schema.load_library()`.

    Returns:
        A Python source string runnable by `tools.execute_cadquery`.

    Raises:
        CompileError: if a step references a primitive missing from the library,
            a primitive lacks a template, or an unsupported operation is used.
    """
    body: list[str] = [_PREAMBLE, f"# part: {plan.part_name} (units: {plan.units})"]
    for index, step in enumerate(plan.steps):
        if isinstance(step, FinishStep):
            body.extend(_compile_finish_step_cq(step))
            body.append("")  # blank line for readability
            continue
        # PrimitiveStep
        spec = library.get(step.primitive)
        if spec is None:
            raise CompileError(
                f"step '{step.id}': primitive '{step.primitive}' is not in the library "
                f"(primitive_gap)"
            )
        body.extend(_step_lines(step, spec, index))
        body.append(_accumulate_line(step, index))
        body.append("")  # blank line between steps for readability
    return "\n".join(body)
