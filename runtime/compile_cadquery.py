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

from runtime.schema import (
    FinishOp,
    FinishStep,
    Operation,
    Pattern,
    PatternType,
    PrimitivePlan,
    PrimitiveStep,
    validate_plan_against_library,
)

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
    Fillet and chamfer are wrapped in try/except because OCCT raises
    StdFail_NotDone when the radius is too large for the geometry — we
    skip rather than crash the whole part.
    """
    lines = [f"# finish '{step.id}' — {step.op.value}"]

    if step.op is FinishOp.fillet:
        sel = step.selector or "|Z"
        lines += [
            "try:",
            f"    result = result.edges({sel!r}).fillet({float(step.value)})",
            "except Exception:",
            f"    pass  # fillet r={step.value} failed on this geometry; skipped",
        ]

    elif step.op is FinishOp.chamfer:
        sel = step.selector or "|Z"
        lines += [
            "try:",
            f"    result = result.edges({sel!r}).chamfer({float(step.value)})",
            "except Exception:",
            f"    pass  # chamfer c={step.value} failed on this geometry; skipped",
        ]

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
        v = (
            list(step.value)
            if isinstance(step.value, list)
            else [step.value, step.value * 1.5, 3.0]
        )
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
        v = (
            list(step.value)
            if isinstance(step.value, list)
            else [step.value, step.value * 1.8, 82.0]
        )
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
    # Enforce semantic validation FIRST: unknown/misnamed params (e.g. giving
    # `pyramid` a `base_length` it doesn't have) would otherwise be silently
    # ignored by _fill_template and fall back to defaults, producing degenerate
    # geometry (a 10x10 spike) that fails downstream as "disconnected components".
    # Raise a primitive_gap CompileError so the loop/preview/temporal all route a
    # clear, actionable message back to the planner instead of building garbage.
    errors = validate_plan_against_library(plan, library)
    if errors:
        raise CompileError("primitive_gap: " + "; ".join(errors))

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
