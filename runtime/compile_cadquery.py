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

from runtime.schema import Operation, Pattern, PatternType, PrimitivePlan, PrimitiveStep

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
        f"{var} = cq.{_fill_template(spec, step.parameters)}",
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
    raise CompileError(
        f"operation '{step.operation.value}' (step '{step.id}') is not supported by the "
        f"CadQuery compiler yet (finish/modifier ops — fillet/chamfer/shell on the body — "
        f"are a planned additive extension; basic fillet/chamfer shapes exist as primitives)"
    )


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
