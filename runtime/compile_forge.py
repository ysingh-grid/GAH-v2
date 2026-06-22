"""Compile a PrimitivePlan into a ForgeCAD (.forge.js) script.

ForgeCAD companion to compile_cadquery.py (segregated per Q6 dual-compiler
design). Fills each primitive's `forge_template` from library.json with step
parameters, places the shape (rotate + translate via _place helper), replicates
via _polar/_linear helpers, and folds CSG operations into a single `result`
returned from the script.

Validation gate (tools/run_forgecad.py):
  forgecad run <file>           — JS + geometry validity
  forgecad export stl <file>    — emit STL for MeshLib pipeline
  forgecad compare 3d <ref.stl> <file> --json   — 0-100 similarity score

Raises CompileForgeError on missing forge_template or unsupported operation;
the geometry loop tags these as `forge_compile` → FailureCategory.translation_drift.
"""

from __future__ import annotations

from typing import Any

from runtime.schema import FinishOp, FinishStep, Operation, Pattern, PatternType, PrimitivePlan, PrimitiveStep

_PREAMBLE = """\
// GAH-v2 generated .forge.js — do not edit; regenerate from plan
// Helpers ─────────────────────────────────────────────────────────────────────
function _place(shape, px, py, pz, rx, ry, rz) {
  let s = shape;
  // ForgeCAD Shape.rotate signature is rotate(axis, angleDeg) — axis FIRST.
  if (rx !== 0) s = s.rotate([1, 0, 0], rx);
  if (ry !== 0) s = s.rotate([0, 1, 0], ry);
  if (rz !== 0) s = s.rotate([0, 0, 1], rz);
  if (px !== 0 || py !== 0 || pz !== 0) s = s.translate(px, py, pz);
  return s;
}
function _polar(shape, count, ax, ay, az, angle_deg) {
  const step = angle_deg / count;
  const copies = Array.from({ length: count }, (_, k) =>
    shape.rotate([ax, ay, az], k * step)
  );
  return union(...copies);
}
function _linear(shape, count, sx, sy, sz) {
  const copies = Array.from({ length: count }, (_, k) =>
    shape.translate(sx * k, sy * k, sz * k)
  );
  return union(...copies);
}
function _torus(ring_r, tube_r) {
  // Approximate torus: polygon profile of a circle at ring_r, revolved around Y.
  const pts = [];
  const steps = 32;
  for (let i = 0; i < steps; i++) {
    const a = (i / steps) * Math.PI * 2;
    pts.push([ring_r + tube_r * Math.cos(a), tube_r * Math.sin(a)]);
  }
  return polygon(pts).revolve();
}
function _ellipsoid(xr, zr) {
  // Half-ellipse profile revolved around Y axis.
  const pts = [[0, -zr]];
  const steps = 32;
  for (let i = 1; i <= steps; i++) {
    const a = (i / steps) * Math.PI;
    pts.push([xr * Math.sin(a), -zr * Math.cos(a)]);
  }
  return polygon(pts).revolve();
}
function _wedge(dx, dy, dz, xmin, ymin, xmax, ymax) {
  // Exact CadQuery/OCC makeWedge: box dx×dy×dz whose top face (y=dy) is shrunk
  // to the rect [xmin,xmax]×[ymin,ymax] (OCC's z-range). Built as a loft from the
  // full bottom rect to the offset top rect along Z, then rotated so the loft axis
  // becomes +Y (CadQuery's frame) and centered. Vertices match CadQuery exactly.
  const bottom = rect(dx, dz);
  const tw = Math.max(0.001, xmax - xmin), th = Math.max(0.001, ymax - ymin);
  const cx = (xmin + xmax) / 2 - dx / 2, cy = dz / 2 - (ymin + ymax) / 2;
  const top = rect(tw, th).translate(cx, cy);
  return loft([bottom, top], [0, dy]).rotate([1, 0, 0], -90).translate(0, -dy / 2, 0);
}
// ─────────────────────────────────────────────────────────────────────────────
"""


class CompileForgeError(Exception):
    """Raised when a plan cannot be turned into a .forge.js script."""


def _fill_forge_template(spec: dict[str, Any], params: dict[str, Any]) -> str:
    """Fill a primitive's forge_template with step params merged over defaults."""
    known = spec.get("parameters", {})
    effective: dict[str, Any] = {name: meta.get("default") for name, meta in known.items()}
    effective.update(params)
    template = spec.get("forge_template")
    if not template:
        raise CompileForgeError(
            f"primitive '{spec.get('name')}' has no forge_template — add it to library.json"
        )
    try:
        filled: str = template.format(**effective)
        return filled
    except KeyError as exc:
        raise CompileForgeError(
            f"forge_template for '{spec.get('name')}' needs parameter {exc} which was not provided"
        ) from exc


def _place_expr(var: str, step: PrimitiveStep) -> str:
    """Return a _place(...) call that applies position + orientation to `var`."""
    px, py, pz = step.position
    rx, ry, rz = step.orientation
    return f"_place({var}, {px}, {py}, {pz}, {rx}, {ry}, {rz})"


def _pattern_expr(var: str, pattern: Pattern) -> str:
    """Return the JS expression that replicates `var` per the pattern spec."""
    if pattern.type is PatternType.polar:
        ax, ay, az = pattern.axis
        return f"_polar({var}, {pattern.count}, {ax}, {ay}, {az}, {pattern.angle_deg})"
    sx, sy, sz = pattern.spacing
    return f"_linear({var}, {pattern.count}, {sx}, {sy}, {sz})"


def _step_lines_forge(step: PrimitiveStep, spec: dict[str, Any], index: int) -> list[str]:
    """Emit JS lines that build, place, and optionally pattern one step."""
    var = f"s{index}"
    shape_expr = _fill_forge_template(spec, dict(step.parameters))
    lines = [
        f"// step '{step.id}' — {step.operation.value} {step.primitive}",
        f"let {var} = {shape_expr};",
        f"{var} = {_place_expr(var, step)};",
    ]
    if step.pattern is not None:
        lines.append(f"{var} = {_pattern_expr(var, step.pattern)};")
    return lines


def _accumulate_forge(step: PrimitiveStep, index: int) -> str:
    """Emit the JS CSG fold line that merges step `index` into `result`."""
    var = f"s{index}"
    if step.operation is Operation.base:
        return f"let result = {var};"
    if step.operation is Operation.union:
        return f"result = result.add({var});"
    if step.operation is Operation.cut:
        return f"result = result.subtract({var});"
    raise CompileForgeError(
        f"operation '{step.operation.value}' (step '{step.id}') is not yet supported by the "
        f"ForgeCAD compiler (finish/modifier ops — post-body fillet/chamfer/shell — "
        f"are a planned extension; use filleted_box/chamfered_box primitives instead)"
    )


def _compile_finish_step_forge(step: FinishStep) -> list[str]:
    """Emit ForgeCAD JS lines that apply a FinishStep to `result`.

    ForgeCAD exposes .fillet(r), .chamfer(r), .shell(t) as chainable methods.
    Holes/counterbores are emitted as cylinder subtractions (no native hole API).
    Fillet/chamfer are wrapped in try/catch — ForgeCAD throws on geometry that
    is too tight for the requested radius.
    """
    lines = [f"// finish '{step.id}' — {step.op.value}"]

    if step.op is FinishOp.fillet:
        r = float(step.value)
        lines += [
            "try {",
            f"  result = result.fillet({r});",
            "} catch(e) {",
            f"  // fillet r={r} skipped: " + "${e}",
            "}",
        ]

    elif step.op is FinishOp.chamfer:
        c = float(step.value)
        lines += [
            "try {",
            f"  result = result.chamfer({c});",
            "} catch(e) {",
            f"  // chamfer c={c} skipped: " + "${e}",
            "}",
        ]

    elif step.op is FinishOp.shell:
        t = abs(float(step.value))  # ForgeCAD shell takes positive wall thickness
        lines.append(f"result = result.shell({t});")

    elif step.op in (FinishOp.hole, FinishOp.cbore, FinishOp.csk):
        # ForgeCAD has no native hole API — emit cylinder subtractions.
        # Use a tall cylinder (height=1000) centred on the face so it punches through.
        if step.op is FinishOp.hole:
            dia = float(step.value)
            r_cyl = dia / 2.0
            positions = step.positions or [(0.0, 0.0)]
        elif step.op is FinishOp.cbore:
            v = list(step.value) if isinstance(step.value, list) else [step.value, step.value * 1.5, 3.0]
            r_cyl = float(v[0]) / 2.0
            positions = step.positions or [(0.0, 0.0)]
        else:  # csk
            v = list(step.value) if isinstance(step.value, list) else [step.value, step.value * 1.8, 82.0]
            r_cyl = float(v[0]) / 2.0
            positions = step.positions or [(0.0, 0.0)]
        for i, (hx, hy) in enumerate(positions):
            lines.append(
                f"const _h{step.id}_{i} = cylinder({r_cyl}, 1000).translate({hx}, {hy}, 0);"
            )
            lines.append(f"result = result.subtract(_h{step.id}_{i});")
    return lines


def compile_plan_to_forge(plan: PrimitivePlan, library: dict[str, Any]) -> str:
    """Compile a PrimitivePlan into a .forge.js script that returns the result shape.

    Args:
        plan: A structurally-valid PrimitivePlan.
        library: Primitives library dict from runtime.schema.load_library().

    Returns:
        A .forge.js source string runnable by `forgecad run`.

    Raises:
        CompileForgeError: if a step primitive is missing from the library,
            lacks a forge_template, or uses an unsupported operation.
    """
    lines: list[str] = [
        _PREAMBLE,
        f"// part: {plan.part_name} (units: {plan.units})",
    ]
    for index, step in enumerate(plan.steps):
        if isinstance(step, FinishStep):
            lines.extend(_compile_finish_step_forge(step))
            lines.append("")
            continue
        # PrimitiveStep
        spec = library.get(step.primitive)
        if spec is None:
            raise CompileForgeError(
                f"step '{step.id}': primitive '{step.primitive}' is not in the library "
                f"(primitive_gap)"
            )
        lines.extend(_step_lines_forge(step, spec, index))
        lines.append(_accumulate_forge(step, index))
        lines.append("")
    lines.append(f'return {{ "{plan.part_name}": result }};')
    return "\n".join(lines)
