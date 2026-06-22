"""
Pydantic schemas and dynamic validation for GAH-v2 primitive plans.
"""

import json
import os
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# Locate the primitives/library.json file relative to this runtime module
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBRARY_PATH = os.path.join(BASE_DIR, "primitives", "library.json")


def load_primitive_library() -> dict[str, Any]:
    """Loads the primitive specification catalog from library.json."""
    if not os.path.exists(LIBRARY_PATH):
        raise FileNotFoundError(f"Primitives library file not found at: {LIBRARY_PATH}")
    with open(LIBRARY_PATH, encoding="utf-8") as f:
        return json.load(f)


# Load library globally on module import
LIBRARY: dict[str, Any] = load_primitive_library()


class PrimitiveItem(BaseModel):
    """Represents a single primitive step in a CAD generation plan."""

    id: str = Field(..., description="Unique identifier for this specific shape step")
    primitive: str = Field(..., description="Primitive name corresponding to library.json catalog")
    operation: Literal["base", "union", "cut"] = Field(
        ..., description="The CSG boolean operation to perform"
    )
    position: list[float] = Field(
        ...,
        min_length=3,
        max_length=3,
        description="XYZ coordinates for centering the shape [x, y, z]",
    )
    orientation: list[float] = Field(
        ...,
        min_length=3,
        max_length=3,
        description="Rotation angles in degrees around the axes [rx, ry, rz]",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Key-value parameters specified in library.json for this primitive",
    )

    @model_validator(mode="after")
    def validate_parameters_against_catalog(self) -> "PrimitiveItem":
        """Ensures the item parameters align exactly with library.json types and specifications."""
        if self.primitive not in LIBRARY:
            raise ValueError(
                f"Unknown primitive type: '{self.primitive}'. Available types: {list(LIBRARY.keys())}"
            )

        spec = LIBRARY[self.primitive]
        allowed_params = spec.get("parameters", {})

        validated_params: dict[str, Any] = {}

        # 1. Verify required parameters and inject defaults if omitted
        for name, param_info in allowed_params.items():
            val = self.parameters.get(name)

            if val is None:
                if "default" in param_info:
                    val = param_info["default"]
                else:
                    raise ValueError(
                        f"Missing required parameter '{name}' for primitive type '{self.primitive}' in step '{self.id}'"
                    )

            # 2. Assert correct type conversion
            expected_type = param_info.get("type", "float")
            try:
                if expected_type == "int":
                    validated_params[name] = int(val)
                elif expected_type == "float":
                    validated_params[name] = float(val)
                else:
                    validated_params[name] = val
            except (TypeError, ValueError) as e:
                raise ValueError(
                    f"Parameter '{name}' for step '{self.id}' must be of type {expected_type}, got value {val}"
                ) from e

        # 3. Reject any unexpected extra parameters
        for name in self.parameters:
            if name not in allowed_params:
                raise ValueError(
                    f"Unexpected parameter '{name}' is not allowed for primitive type '{self.primitive}' in step '{self.id}'"
                )

        self.parameters = validated_params
        return self


class PrimitivePlan(BaseModel):
    """Represents a complete sequence of steps to assemble a CAD solid."""

    plan: list[PrimitiveItem] = Field(..., description="Ordered list of primitive steps")

    @model_validator(mode="after")
    def validate_plan_logic(self) -> "PrimitivePlan":
        """Validates sequential plan logic (e.g. starting with base shape)."""
        if not self.plan:
            raise ValueError("Primitive plan must contain at least one step.")

        # The first step MUST be the "base" operation
        if self.plan[0].operation != "base":
            raise ValueError(
                f"The first step in the plan (step: '{self.plan[0].id}') must have operation='base'. Got '{self.plan[0].operation}'."
            )

        # Subsequent steps MUST NOT have "base" operation
        for item in self.plan[1:]:
            if item.operation == "base":
                raise ValueError(
                    f"Invalid plan logic: step '{item.id}' has operation='base' but is not the first step. Only the initial step can be 'base'."
                )

        return self
