"""Build an augmented CadQuery script that PREVIEWS a plan with real geometry.

WHY: the planner is text-only and plans blind. `preview_plan` (Task 5) lets it
see the REAL geometry of a candidate plan — does it compile, is it one watertight
solid, and how big is each feature relative to the whole — as structured text it
can act on inside its REPL, before emitting FINAL.

This module is the deterministic half: it turns a PrimitivePlan into a script.
The compiler already emits per-step variables `s0, s1, ...` (one per PrimitiveStep,
in plan order) plus the accumulated `result`. We reuse that verbatim and append a
diagnostic epilogue that measures each `s{i}`'s bounding box, exports the STL/STEP,
and prints one JSON object. The whole thing is wrapped in try/except so a runtime
boolean failure comes back as structured JSON, not a raw crash.
"""

from __future__ import annotations

import textwrap
from typing import Any

from runtime.compile_cadquery import compile_plan_to_cadquery
from runtime.schema import PrimitivePlan, PrimitiveStep


def _perstep_specs(plan: PrimitivePlan) -> list[tuple[str, str, str, str]]:
    """(var_name, step_id, operation, primitive) for each PrimitiveStep, in order.

    var_name matches the compiler's naming: the Nth plan step (0-based, counting
    FinishSteps too, since the compiler enumerates all steps) that is a
    PrimitiveStep is stored in `sN`.
    """
    specs: list[tuple[str, str, str, str]] = []
    for index, step in enumerate(plan.steps):
        if isinstance(step, PrimitiveStep):
            specs.append((f"s{index}", step.id, step.operation.value, step.primitive))
    return specs


def _epilogue(specs: list[tuple[str, str, str, str]], stl_path: str, step_path: str) -> str:
    """Code that exports the solid, measures overall + per-step bboxes, fills _out."""
    solids = ",\n        ".join(
        f'("{sid}", "{op}", "{prim}", {var})' for var, sid, op, prim in specs
    )
    return textwrap.dedent(
        f"""
        import cadquery as _cq
        import os as _os
        _os.makedirs(_os.path.dirname({stl_path!r}), exist_ok=True)
        _cq.exporters.export(result, {stl_path!r})
        _cq.exporters.export(result, {step_path!r})
        _shape = result.val() if hasattr(result, "val") else result
        _bb = _shape.BoundingBox()
        _out["volume"] = _shape.Volume()
        _out["bbox"] = {{"xmin": _bb.xmin, "ymin": _bb.ymin, "zmin": _bb.zmin,
                         "xmax": _bb.xmax, "ymax": _bb.ymax, "zmax": _bb.zmax}}
        _out["faces_count"] = len(_shape.Faces())
        _out["stl_path"] = {stl_path!r}
        _out["step_path"] = {step_path!r}
        _solids = [
        {solids}
        ]
        _pf = []
        for _sid, _op, _prim, _sol in _solids:
            try:
                _s = _sol.val() if hasattr(_sol, "val") else _sol
                _b = _s.BoundingBox()
                _pf.append({{
                    "id": _sid, "operation": _op, "primitive": _prim,
                    "bbox": {{"xmin": _b.xmin, "ymin": _b.ymin, "zmin": _b.zmin,
                              "xmax": _b.xmax, "ymax": _b.ymax, "zmax": _b.zmax}},
                    "size_mm": [round(_b.xmax - _b.xmin, 2), round(_b.ymax - _b.ymin, 2),
                                round(_b.zmax - _b.zmin, 2)],
                }})
            except Exception as _e:
                _pf.append({{"id": _sid, "operation": _op, "primitive": _prim, "error": str(_e)}})
        _out["per_feature"] = _pf
        """
    )


def build_preview_script(
    plan: PrimitivePlan, library: dict[str, Any], stl_path: str, step_path: str
) -> str:
    """Return a self-contained CadQuery script that previews the plan.

    Raises CompileError (from the compiler) if the plan can't be turned into code
    at all — the caller treats that as compiles=False.
    """
    body = compile_plan_to_cadquery(plan, library)
    specs = _perstep_specs(plan)
    epilogue = _epilogue(specs, stl_path, step_path)
    inner = textwrap.indent(body + "\n" + epilogue, "    ")
    return (
        "import json as _json\n"
        "import traceback as _tb\n"
        "_out = {'success': True}\n"
        "try:\n"
        f"{inner}\n"
        "except Exception:\n"
        "    _out = {'success': False, 'error': _tb.format_exc()}\n"
        "print(_json.dumps(_out))\n"
    )
