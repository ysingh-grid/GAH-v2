"""PrimitivePlan — the typed contract the whole runtime speaks.

A PrimitivePlan describes ONE part as an ordered list of CSG steps. Each step
names a library primitive, an operation (base / union / cut / finish), its
parameters, and a placement. A step may optionally carry a `pattern` that
replicates it (polar or linear array) before the boolean is applied.

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
    """Role a step plays in the CSG construction of the single part."""

    base = "base"  # the starting solid; exactly one, must be first
    union = "union"  # fuse this primitive onto the accumulating body
    cut = "cut"  # subtract this primitive from the accumulating body
    finish = "finish"  # modifier on the current body (fillet / chamfer / shell)


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
        if self.pattern is not None and self.operation not in (Operation.union, Operation.cut):
            raise ValueError(
                f"step '{self.id}': pattern is only valid on union/cut steps, "
                f"not '{self.operation.value}'"
            )
        return self


class PrimitivePlan(BaseModel):
    """An ordered CSG recipe that produces one part."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    part_name: str = Field(min_length=1)
    units: str = "mm"
    steps: list[PrimitiveStep] = Field(min_length=1)

    @field_validator("units")
    @classmethod
    def _units_supported(cls, v: str) -> str:
        if v != "mm":
            raise ValueError(f"only 'mm' units are supported in the MVP, got '{v}'")
        return v

    @model_validator(mode="after")
    def _structural_rules(self) -> PrimitivePlan:
        ids = [s.id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step ids must be unique")

        base_indexes = [i for i, s in enumerate(self.steps) if s.operation is Operation.base]
        if len(base_indexes) != 1:
            raise ValueError(f"plan must have exactly one 'base' step, found {len(base_indexes)}")
        if base_indexes[0] != 0:
            raise ValueError("the 'base' step must be the first step in the plan")
        return self


def plan_from_dict(data: dict[str, Any]) -> PrimitivePlan:
    """Parse + structurally validate a plan dict (raises pydantic ValidationError)."""
    return PrimitivePlan.model_validate(data)


def plan_to_dict(plan: PrimitivePlan) -> dict[str, Any]:
    """Serialize a plan back to a plain JSON-able dict."""
    return plan.model_dump(mode="json")


def load_library(library_path: Path | None = None) -> dict[str, Any]:
    """Load the primitives library JSON.

    Convenience for callers in `runtime/` that need the library without
    importing the `tools/` or `backend/` loaders. Pure read of the JSON file.
    """
    path = library_path or _LIBRARY_PATH
    with open(path, encoding="utf-8") as f:
        library: dict[str, Any] = json.load(f)
    return library


def _check_step_against_library(step: PrimitiveStep, library: dict[str, Any]) -> list[str]:
    """Return semantic errors for one step against the library (empty == ok)."""
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
