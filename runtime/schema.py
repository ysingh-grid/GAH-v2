"""PrimitivePlan — the typed contract the whole runtime speaks.

A PrimitivePlan describes ONE part as an ordered list of CSG steps. Each step
names a library primitive, an operation (base / union / cut / intersect), its
parameters, and a placement. A step may optionally carry a `pattern` that
replicates it (polar or linear array) before the boolean is applied. Post-body
modifiers (fillet / chamfer / shell / holes / mirror) are separate FinishSteps.

This module is intentionally split into two layers:

* **Structural validation** — the pydantic models below. They guarantee the
  plan is well-formed in isolation (unique ids, exactly one leading `base`,
  patterns only on boolean steps, etc.). No file I/O, no library knowledge.
* **Semantic validation** — `validate_plan_against_library(plan, library)`.
  A pure function that checks the plan against a primitives library dict
  (primitive names exist, parameter keys are known, types are sane). The
  caller supplies the library so `runtime/` stays free of `tools/` and
  `backend/` imports.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# A primitive parameter is a scalar, a flat list (e.g. an axis), or a list of
# points (e.g. a 2D profile for profile_extrude / revolve).
ParamScalar = float | int
ParamValue = ParamScalar | list[float] | list[list[float]]

_LIBRARY_PATH = Path(__file__).resolve().parent.parent / "primitives" / "library.json"


class Operation(StrEnum):
    """Role a step plays in the CSG construction of the single part.

    base/union/cut/intersect are the four CSG folds. Post-body modifiers
    (fillet/chamfer/shell/holes/mirror) are NOT operations here — they are
    separate FinishStep entries with their own FinishOp.
    """

    base = "base"  # the starting solid; exactly one, must be first
    union = "union"  # fuse this primitive onto the accumulating body
    cut = "cut"  # subtract this primitive from the accumulating body
    intersect = "intersect"  # keep only the overlap of this primitive and the body


class FinishOp(StrEnum):
    """Post-body finish operations the deterministic compilers can apply."""

    fillet = "fillet"    # round selected edges:  value = radius (mm)
    chamfer = "chamfer"  # bevel selected edges:  value = chamfer length (mm)
    shell = "shell"      # hollow the body:       value = wall thickness (mm, positive=inward)
    hole = "hole"        # drill a through-hole:  value = diameter (mm), positions = [[x,y],...]
    cbore = "cbore"      # counterbored hole:     value = [clr_dia, bore_dia, bore_depth] (mm)
    csk = "csk"          # countersunk hole:      value = [clr_dia, csk_dia, csk_angle_deg]
    mirror = "mirror"    # mirror body across a plane & union w/ original; selector = plane ("XZ")


class PatternType(StrEnum):
    """How a patterned step replicates its primitive."""

    polar = "polar"  # rotate copies about `axis` through the origin
    linear = "linear"  # translate copies by `spacing` each


class Pattern(BaseModel):
    """Replication applied to a single step before its boolean op runs.

    Polar: `count` copies spread over `angle_deg` about `axis`.
    Linear: `count` copies, each offset from the last by `spacing`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: PatternType
    count: int = Field(ge=2, le=200)
    axis: tuple[float, float, float] = (0.0, 0.0, 1.0)
    angle_deg: float = 360.0
    spacing: tuple[float, float, float] = (0.0, 0.0, 0.0)


class FinishStep(BaseModel):
    """A post-body modifier: fillet/chamfer edges, shell, or drill holes.

    FinishSteps are NOT primitives. They act on the accumulated `result` solid
    produced by all preceding PrimitiveSteps. They are compiled deterministically
    by both compile_cadquery and compile_forge.

    Fields:
        id:        Unique step identifier.
        op:        Which finish operation to apply.
        selector:  CadQuery-style selector string for the target edges/faces.
                   e.g. "|Z" (all vertical edges), ">Z" (top face), "%Circle" (circular edges).
                   Ignored for 'hole'/'cbore'/'csk' (positions-based).
        value:     Numeric parameter(s) for the operation:
                   fillet/chamfer  → float radius or length
                   shell           → float wall thickness (positive = inward)
                   hole            → float diameter
                   cbore           → [clr_dia, bore_dia, bore_depth]
                   csk             → [clr_dia, csk_dia, csk_angle_deg]
        positions: For hole/cbore/csk: list of (x, y) points on the face where
                   holes are drilled. If empty and op is hole/cbore/csk, the hole
                   is placed at the origin of the selected face.
        face:      Face selector for where holes are drilled (default ">Z" = top face).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    op: FinishOp
    selector: str = ""          # edge/face selector (CadQuery string)
    value: ParamValue = 1.0     # operation parameter(s)
    positions: list[tuple[float, float]] = Field(default_factory=list)
    face: str = ">Z"            # face for hole ops


class PrimitiveStep(BaseModel):
    """One CSG step: a placed (optionally patterned) library primitive."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    primitive: str = Field(min_length=1)
    operation: Operation
    parameters: dict[str, ParamValue] = Field(default_factory=dict)
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    orientation: tuple[float, float, float] = (0.0, 0.0, 0.0)  # degrees about X, Y, Z
    pattern: Pattern | None = None

    @model_validator(mode="after")
    def _pattern_only_on_booleans(self) -> PrimitiveStep:
        if self.pattern is not None and self.operation not in (
            Operation.union,
            Operation.cut,
            Operation.intersect,
        ):
            raise ValueError(
                f"step '{self.id}': pattern is only valid on union/cut/intersect steps, "
                f"not '{self.operation.value}'"
            )
        return self


# A plan step is either a primitive CSG step or a post-body finish modifier.
AnyStep = PrimitiveStep | FinishStep


class PrimitivePlan(BaseModel):
    """An ordered CSG recipe that produces one part.

    Compile semantics (two-phase, general — not per-object recipes):
    additive steps (base/union/intersect) build the body; all cut steps are
    fused into one cavity tool and subtracted once; finish steps apply last.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    part_name: str = Field(min_length=1)
    units: str = "mm"
    steps: list[AnyStep] = Field(min_length=1)

    @field_validator("units")
    @classmethod
    def _units_supported(cls, v: str) -> str:
        if v != "mm":
            raise ValueError(f"only 'mm' units are supported in the MVP, got '{v}'")
        return v

    @model_validator(mode="before")
    @classmethod
    def _coerce_extra_bases(cls, data: Any) -> Any:
        """Deterministically fold multiple 'base' steps into one legal compound.

        A Case-A multi-solid plan (bolt+nut, flange-kit) has N independent
        bodies. Each body's own root primitive reads naturally as 'base', so the
        planner routinely emits N bases — but the schema requires exactly one,
        and the documented-correct form (playbook: "only the FIRST body is base,
        every other is union; a union of disjoint solids is one multi-component
        compound") is an unambiguous rewrite. Apply it here instead of bouncing
        the whole plan through an expensive cold replan for a mechanical rule.
        Only the FIRST primitive 'base' is kept; later 'base' steps → 'union'.
        """
        if not isinstance(data, dict):
            return data
        steps = data.get("steps")
        if not isinstance(steps, list):
            return data
        seen_base = False
        for s in steps:
            # PrimitiveStep carries "operation"; FinishStep carries "op" — the
            # latter has no operation key, so it's skipped by this guard.
            if isinstance(s, dict) and s.get("operation") == "base":
                if seen_base:
                    s["operation"] = "union"
                else:
                    seen_base = True
        return data

    @model_validator(mode="after")
    def _structural_rules(self) -> PrimitivePlan:
        ids = [s.id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step ids must be unique")

        # Only PrimitiveSteps contribute to the base-step rule.
        primitive_steps = [s for s in self.steps if isinstance(s, PrimitiveStep)]
        base_indexes = [i for i, s in enumerate(primitive_steps) if s.operation is Operation.base]
        if len(base_indexes) != 1:
            raise ValueError(f"plan must have exactly one 'base' PrimitiveStep, found {len(base_indexes)}")
        if base_indexes[0] != 0:
            raise ValueError("the 'base' PrimitiveStep must be the first primitive step in the plan")
        return self


def plan_from_dict(data: dict[str, Any]) -> PrimitivePlan:
    """Parse + structurally validate a plan dict (raises pydantic ValidationError)."""
    return PrimitivePlan.model_validate(data)


def plan_to_dict(plan: PrimitivePlan) -> dict[str, Any]:
    """Serialize a plan back to a plain JSON-able dict."""
    return plan.model_dump(mode="json")


class LibraryBoundPrimitivePlan(PrimitivePlan):
    """PrimitivePlan that ALSO enforces library params + construction guards.

    Used as fast-rlm `output_schema` so wrong param names / illegal constructions
    fail at FINAL (schema-retry inside the RLM call) instead of as a later
    Temporal geometry-loop `primitive_gap` / multi-body thrash.
    """

    @model_validator(mode="after")
    def _library_and_construction(self) -> LibraryBoundPrimitivePlan:
        library = load_library()
        errors = validate_plan_against_library(self, library)
        if errors:
            # ValueError → pydantic validation error → fast-rlm FINAL retry with text.
            raise ValueError("primitive_gap: " + "; ".join(errors))
        from runtime.plan_guards import construction_errors_for_plan

        construction = construction_errors_for_plan(self)
        if construction:
            raise ValueError("; ".join(construction))
        return self


def accept_plan(data: Any) -> PrimitivePlan:
    """Full host accept: structure + library + construction (raises ValueError/ValidationError)."""
    if isinstance(data, LibraryBoundPrimitivePlan):
        return data
    if isinstance(data, PrimitivePlan):
        return LibraryBoundPrimitivePlan.model_validate(plan_to_dict(data))
    return LibraryBoundPrimitivePlan.model_validate(data)


def compact_library_menu(library: dict[str, Any] | None = None) -> dict[str, Any]:
    """Rich menu: description + param names/types/defaults for every primitive.

    ~6k chars for the full catalog — small enough to preload so the planner does
    not invent pretrained param names (ring_radius) that become primitive_gap.
    """
    lib = library if library is not None else load_library()
    menu: dict[str, Any] = {}
    for name, spec in lib.items():
        params_out: dict[str, Any] = {}
        for pname, meta in (spec.get("parameters") or {}).items():
            if not isinstance(meta, dict):
                continue
            params_out[pname] = {
                "type": meta.get("type", "float"),
                "default": meta.get("default"),
            }
        menu[name] = {
            "description": spec.get("description", ""),
            "parameters": params_out,
        }
    return menu


def load_library(library_path: Path | None = None) -> dict[str, Any]:
    """Load the primitives library JSON.

    Convenience for callers in `runtime/` that need the library without
    importing the `tools/` or `backend/` loaders. Pure read of the JSON file.
    """
    path = library_path or _LIBRARY_PATH
    with open(path, encoding="utf-8") as f:
        library: dict[str, Any] = json.load(f)
    return library


def _check_step_against_library(
    step: AnyStep, library: dict[str, Any]
) -> list[str]:
    """Return semantic errors for one step against the library (empty == ok)."""
    # FinishSteps have no primitive — nothing to check against the library.
    if isinstance(step, FinishStep):
        return []

    errors: list[str] = []
    spec = library.get(step.primitive)
    if spec is None:
        supported = ", ".join(sorted(library)) or "<empty library>"
        errors.append(
            f"step '{step.id}': primitive '{step.primitive}' is not in the library "
            f"(primitive_gap). Supported: {supported}"
        )
        return errors  # nothing else checkable without a spec

    known_params: dict[str, Any] = spec.get("parameters", {})
    for key, value in step.parameters.items():
        if key not in known_params:
            errors.append(
                f"step '{step.id}': unknown parameter '{key}' for primitive "
                f"'{step.primitive}'. Known: {', '.join(known_params) or '<none>'}"
            )
            continue
        expected = known_params[key].get("type")
        if expected == "int" and not isinstance(value, int):
            errors.append(
                f"step '{step.id}': parameter '{key}' expects int, got {type(value).__name__}"
            )
        elif expected == "float" and not isinstance(value, (int, float)):
            errors.append(
                f"step '{step.id}': parameter '{key}' expects float, got {type(value).__name__}"
            )
    return errors


def validate_plan_against_library(plan: PrimitivePlan, library: dict[str, Any]) -> list[str]:
    """Check a structurally-valid plan against a primitives library.

    Args:
        plan: A PrimitivePlan that already passed structural validation.
        library: The primitives library dict (name -> spec), e.g. from
            `load_library()`.

    Returns:
        A list of human-readable error strings. Empty list == the plan is
        semantically valid and every primitive it uses exists in the library.
        Missing primitives are reported as `primitive_gap` so the caller can
        tag the failure taxonomy correctly.
    """
    errors: list[str] = []
    for step in plan.steps:
        errors.extend(_check_step_against_library(step, library))
    return errors
