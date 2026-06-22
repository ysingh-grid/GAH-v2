"""Reusable real-world CAD scenarios for tests.

Each scenario starts from a plain-language user prompt and includes the
PrimitivePlan we expect the planner to produce. Tests can then exercise the
actual runtime stages without re-declaring bulky plans in every file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.schema import PrimitivePlan, plan_from_dict


@dataclass(frozen=True)
class CadScenario:
    """A realistic user request plus the validated PrimitivePlan for it."""

    name: str
    prompt: str
    plan: PrimitivePlan
    expected_bbox: dict[str, float]
    solid_reference_volume: float | None = None


def mounting_plate_with_four_holes() -> CadScenario:
    """Return a flat electronics mounting plate with four M3 clearance holes."""
    return CadScenario(
        name="mounting_plate_four_holes",
        prompt=(
            "Design an 80 mm by 50 mm by 6 mm electronics mounting plate with four "
            "3.2 mm diameter through-holes, one near each corner, centered 30 mm "
            "from the X origin and 18 mm from the Y origin."
        ),
        plan=plan_from_dict(
            {
                "part_name": "electronics_mounting_plate",
                "steps": [
                    {
                        "id": "plate",
                        "primitive": "box",
                        "operation": "base",
                        "parameters": {"length": 80.0, "width": 50.0, "height": 6.0},
                    },
                    {
                        "id": "left_hole_pair",
                        "primitive": "cylinder",
                        "operation": "cut",
                        "parameters": {"radius": 1.6, "height": 12.0},
                        "position": [-30.0, -18.0, 0.0],
                        "pattern": {"type": "linear", "count": 2, "spacing": [0.0, 36.0, 0.0]},
                    },
                    {
                        "id": "right_hole_pair",
                        "primitive": "cylinder",
                        "operation": "cut",
                        "parameters": {"radius": 1.6, "height": 12.0},
                        "position": [30.0, -18.0, 0.0],
                        "pattern": {"type": "linear", "count": 2, "spacing": [0.0, 36.0, 0.0]},
                    },
                ],
            }
        ),
        expected_bbox={"x": 80.0, "y": 50.0, "z": 6.0},
        solid_reference_volume=80.0 * 50.0 * 6.0,
    )


def open_electronics_enclosure() -> CadScenario:
    """Return a common enclosure body with bosses and vertical screw holes."""
    return CadScenario(
        name="open_electronics_enclosure",
        prompt=(
            "Design a 70 mm by 50 mm by 30 mm open-top electronics enclosure body "
            "with 2 mm wall thickness, four internal screw bosses, and vertical "
            "3 mm screw holes through each boss."
        ),
        plan=plan_from_dict(
            {
                "part_name": "open_electronics_enclosure",
                "steps": [
                    {
                        "id": "shell",
                        "primitive": "hollow_box",
                        "operation": "base",
                        "parameters": {
                            "length": 70.0,
                            "width": 50.0,
                            "height": 30.0,
                            "wall_thickness": 2.0,
                        },
                    },
                    {
                        "id": "front_left_boss",
                        "primitive": "cylinder",
                        "operation": "union",
                        "parameters": {"radius": 4.0, "height": 26.0},
                        "position": [-27.0, -17.0, 2.0],
                    },
                    {
                        "id": "front_right_boss",
                        "primitive": "cylinder",
                        "operation": "union",
                        "parameters": {"radius": 4.0, "height": 26.0},
                        "position": [27.0, -17.0, 2.0],
                    },
                    {
                        "id": "rear_left_boss",
                        "primitive": "cylinder",
                        "operation": "union",
                        "parameters": {"radius": 4.0, "height": 26.0},
                        "position": [-27.0, 17.0, 2.0],
                    },
                    {
                        "id": "rear_right_boss",
                        "primitive": "cylinder",
                        "operation": "union",
                        "parameters": {"radius": 4.0, "height": 26.0},
                        "position": [27.0, 17.0, 2.0],
                    },
                    {
                        "id": "boss_holes_left",
                        "primitive": "cylinder",
                        "operation": "cut",
                        "parameters": {"radius": 1.5, "height": 40.0},
                        "position": [-27.0, -17.0, 2.0],
                        "pattern": {"type": "linear", "count": 2, "spacing": [0.0, 34.0, 0.0]},
                    },
                    {
                        "id": "boss_holes_right",
                        "primitive": "cylinder",
                        "operation": "cut",
                        "parameters": {"radius": 1.5, "height": 40.0},
                        "position": [27.0, -17.0, 2.0],
                        "pattern": {"type": "linear", "count": 2, "spacing": [0.0, 34.0, 0.0]},
                    },
                ],
            }
        ),
        expected_bbox={"x": 70.0, "y": 50.0, "z": 30.0},
    )


def bbox_size(bbox: dict[str, Any], axis: str) -> float:
    """Return a bounding-box size from execute_cadquery's bbox dict."""
    return float(bbox[f"{axis}max"] - bbox[f"{axis}min"])
