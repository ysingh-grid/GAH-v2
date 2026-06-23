import json
import os
from pathlib import Path
from pydantic import BaseModel, Field, model_validator, create_model
from typing import Dict, List, Optional, Any, Literal, Union
from typing_extensions import Annotated

# Load primitives registry at module level for reference/fallback (portable).
primitives_path = Path(__file__).parent / "primitives.json"
if not primitives_path.exists() and os.environ.get("PRIMITIVES_JSON"):
    primitives_path = Path(os.environ["PRIMITIVES_JSON"])

try:
    with open(primitives_path, "r", encoding="utf-8") as f:
        PRIMITIVES_REGISTRY = json.load(f)
except Exception:
    PRIMITIVES_REGISTRY = {}

# Load standard allowed CadQuery operations
FALLBACK_CQ_OPERATIONS = {
    # 2D operations
    "Workplane.center", "Workplane.circle", "Workplane.ellipse", "Workplane.rect",
    "Workplane.polyline", "Workplane.line", "Workplane.lineTo", "Workplane.moveTo",
    "Workplane.spline", "Workplane.tangentArcPoint", "Workplane.threePointArc",
    "Workplane.slot2D", "Workplane.polarArray", "Workplane.rarray", "Workplane.pushPoints",
    # 3D operations
    "Workplane.box", "Workplane.cylinder", "Workplane.extrude", "Workplane.hole",
    "Workplane.loft", "Workplane.revolve", "Workplane.sweep", "Workplane.chamfer",
    "Workplane.fillet", "Workplane.shell", "Workplane.union", "Workplane.cut",
    "Workplane.intersect", "Workplane.cboreHole", "Workplane.cskHole",
    "Workplane.cutBlind", "Workplane.cutThruAll",
    # Sketch & others
    "Workplane.sketch", "Sketch.rect", "Sketch.circle", "Sketch.ellipse",
    "Sketch.polygon", "Sketch.slot", "Sketch.hull", "Sketch.offset"
}

kb_json_path = Path(__file__).parent.parent / "cadquery_kb_pack" / "knowledge" / "cadquery_kb.json"
ALLOWED_CQ_OPERATIONS = FALLBACK_CQ_OPERATIONS.copy()
if kb_json_path.exists():
    try:
        with open(kb_json_path, "r", encoding="utf-8") as f:
            kb_data = json.load(f)
            for entry in kb_data.get("api", []):
                if "id" in entry:
                    ALLOWED_CQ_OPERATIONS.add(entry["id"])
            for cat, ops in kb_data.get("categories", {}).items():
                for op in ops:
                    ALLOWED_CQ_OPERATIONS.add(op)
    except Exception:
        pass


# Helper to convert type string to Python type
def _get_python_type(type_str: str):
    if type_str == "int":
        return int
    elif type_str == "float":
        return float
    elif type_str == "str":
        return str
    elif type_str == "bool":
        return bool
    return float  # Default to float


# Dynamically construct parameter and step models for each primitive in the registry
DYNAMIC_STEP_MODELS = []


ANCHOR_NAMES = ["top", "bottom", "left", "right", "front", "back", "center"]


class AttachSpec(BaseModel):
    """Relational placement (a 'mate'): position THIS step by anchoring it to another
    part, so the kernel DERIVES the coordinates and the parts touch by construction —
    instead of the planner guessing absolute positions that may leave gaps."""
    model_config = {"extra": "forbid"}
    to: Union[str, int] = Field(description="Target step to attach to: its `name` or its sequence_id")
    at: Literal["top", "bottom", "left", "right", "front", "back", "center"] = Field(
        description="Which anchor on the TARGET part to attach to")
    my_anchor: Optional[Literal["top", "bottom", "left", "right", "front", "back", "center"]] = Field(
        default=None, description="Which anchor on THIS part meets the target (defaults to the opposite of `at`)")
    gap: float = Field(default=0.0, description="Gap in mm along the mate normal; 0 = touching/fused")



for prim_name, prim_data in PRIMITIVES_REGISTRY.items():
    # 1. Build Parameter Model Fields
    param_fields = {}
    for p_name, p_info in prim_data.get("parameters", {}).items():
        p_type_str = p_info.get("type", "float")
        p_desc = p_info.get("description", "")
        p_default = p_info.get("default")
        python_type = _get_python_type(p_type_str)
        
        # Pydantic field definition (tuple of (type, Field))
        if python_type in (int, float):
            is_coord = p_name in ("xmin", "ymin", "xmax", "ymax", "taper_angle")
            is_top_dia = p_name == "top_diameter"
            if not is_coord and not is_top_dia:
                param_fields[p_name] = (python_type, Field(default=p_default, gt=0, description=p_desc))
            elif is_top_dia:
                param_fields[p_name] = (python_type, Field(default=p_default, ge=0, description=p_desc))
            else:
                param_fields[p_name] = (python_type, Field(default=p_default, description=p_desc))
        elif python_type == int and p_name == "sides":
            param_fields[p_name] = (int, Field(default=p_default, ge=3, description=p_desc))
        else:
            param_fields[p_name] = (python_type, Field(default=p_default, description=p_desc))
            
    # Create the parameters subclass model
    param_class_name = f"{prim_name.title().replace('_', '')}Params"
    param_model = create_model(
        param_class_name,
        __config__={"extra": "forbid"},
        **param_fields
    )
    globals()[param_class_name] = param_model
    
    # 2. Build Step Model Fields
    step_class_name = f"{prim_name.title().replace('_', '')}Step"
    step_model = create_model(
        step_class_name,
        __config__={"extra": "forbid"},
        sequence_id=(int, Field(description="Sequence step number starting from 1")),
        name=(str, Field(default="", description="Descriptive name of this part/step")),
        primitive_type=(Literal[prim_name], Field(description="Type of primitive")),
        parameters=(param_model, Field(description=f"Parameters for {prim_name} primitive")),
        operation=(Literal["new", "join", "cut", "intersect"], Field(default="new", description="How this step combines with the running result: new (add body), join (union), cut (subtract), intersect")),
        position=(List[float], Field(default_factory=lambda: [0.0, 0.0, 0.0], description="[x, y, z] mm translation. CRITICAL WARNING: DO NOT guess absolute coordinates for parts that must connect. You will cause floating-point gaps and broken assemblies. For connected pieces, you MUST use 'attach' and leave 'position' empty. This field should ONLY be used for entirely disconnected free-floating bodies.")),
        rotation=(List[float], Field(default_factory=lambda: [0.0, 0.0, 0.0], description="[rx, ry, rz] degrees rotation applied to this step before combining")),
        attach=(Optional[AttachSpec], Field(default=None, description="Relational placement: mate this part to another instead of guessing absolute coordinates. The kernel derives the position so they touch. This MUST be used for parts that connect.")),

        part=(Optional[str], Field(default=None, description="Assembly part this step belongs to (only used when assembly_kind='assembly')")),
        rationale=(str, Field(description="Short explanation of how this primitive addresses requirements")),
    )
    globals()[step_class_name] = step_model
    DYNAMIC_STEP_MODELS.append(step_model)


# ==========================================
# Custom / Freeform step schema
# ==========================================

class CustomParams(BaseModel):
    model_config = {"extra": "forbid"}
    shape_description: str = Field(description="What this freeform step builds, in plain words")
    cadquery_operations: List[str] = Field(
        description="CadQuery operation ids actually used, taken from the KB "
                    "(e.g. ['Workplane.polyline','Workplane.extrude','Workplane.hole']). "
                    "Look them up via cadquery_search/cadquery_doc; never invent them.")
    code_sketch: str = Field(
        description="CRITICAL: This MUST be the actual Python source code using CadQuery that builds this shape and assigns it to a variable named `result` (e.g., `result = cq.Workplane('XY').extrude(10)`). Do NOT write English text or pseudocode here! Write valid Python code only.")
    declared_dimensions: Dict[str, float] = Field(
        default_factory=dict,
        description="Key dimensions you intend to build — the contract the verifier "
                    "will later audit declared-vs-measured.")

    @model_validator(mode="after")
    def validate_cadquery_operations(self) -> 'CustomParams':
        # A custom step with no real code is invalid — catch it HERE (cheap) instead of
        # letting it pass validation and fail later at build.
        cs = (self.code_sketch or "").strip()
        if not cs:
            raise ValueError(
                "CRITICAL ERROR: custom step code_sketch is EMPTY. A custom step must contain the actual "
                "CadQuery Python code that builds the shape (e.g. result = cq.Workplane('XY')...). "
                "Write the valid Python code, do not leave it blank.")
        if "cq." not in cs and "Workplane" not in cs and "cadquery" not in cs:
            raise ValueError(
                "CRITICAL ERROR: custom step code_sketch does not contain CadQuery code (expected something "
                "like cq.Workplane(...)). You likely wrote English text instead of code! "
                "You MUST write valid Python source code using CadQuery, and assign the final shape to `result`. Do NOT write natural language descriptions.")
        # The curated CadQuery KB is a SUBSET of CadQuery's real API — "not in the KB" does
        # NOT mean "invalid" (e.g. Edge.fillet is real but may not be curated). So this is a
        # FORGIVING check: accept any operation in a real CadQuery namespace. The actual
        # correctness gate for custom code is the BUILD stage, which executes the code_sketch.
        import re
        _CQ_NAMESPACES = ("Workplane", "Sketch", "Solid", "Shape", "Edge", "Face", "Wire",
                          "Vertex", "Vector", "Plane", "Assembly", "Compound", "Shell", "CQ")
        pat = re.compile(r"^(cq\.)?(" + "|".join(_CQ_NAMESPACES) + r")\.\w+$")
        invalid_ops = [op for op in self.cadquery_operations
                       if op not in ALLOWED_CQ_OPERATIONS and not pat.match(op)]
        if invalid_ops:
            raise ValueError(
                f"Unrecognized CadQuery operations in custom step: {invalid_ops}. "
                "Use real CadQuery operations (e.g. Workplane.extrude, Edge.fillet, Sketch.arc); "
                "browse them with cadquery_search/cadquery_doc."
            )
        return self


class CustomStep(BaseModel):
    sequence_id: int = Field(description="Sequence step number starting from 1")
    name: str = Field(default="", description="Descriptive name of this part/step")
    primitive_type: Literal["custom"] = Field(description="Freeform CadQuery step (no primitive fits)")
    parameters: CustomParams = Field(description="The freeform CadQuery operation plan")
    operation: Literal["new", "join", "cut", "intersect"] = Field(default="new", description="How this step combines with the running result")
    position: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], description="[x, y, z] mm translation. Acts as an absolute coordinate, OR as a relative offset if 'attach' is used.")
    rotation: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], description="[rx, ry, rz] degrees rotation applied before combining")
    attach: Optional[AttachSpec] = Field(default=None, description="Relational placement: attach to another part instead of absolute position")
    part: Optional[str] = Field(default=None, description="Assembly part this step belongs to (only used when assembly_kind='assembly')")
    rationale: str = Field(description="Why no primitive can represent this shape, so a freeform step is required")
    trust_tier: Literal["needs_review"] = Field(default="needs_review", description="Freeform geometry is never auto-certified")


# Dynamic Union of all supported steps discriminated by primitive_type
PrimitiveStep = Annotated[
    Union[tuple(DYNAMIC_STEP_MODELS + [CustomStep])],
    Field(discriminator="primitive_type")
]


# ==========================================
# Overall Geometry Plan Model
# ==========================================

class GeometryPlan(BaseModel):
    class OverallDimensions(BaseModel):
        width: float = Field(description="Overall width of the bounding box in mm")
        length: float = Field(description="Overall length of the bounding box in mm")
        height: float = Field(description="Overall height of the bounding box in mm")

    class EngineeringRequirements(BaseModel):
        functional: List[str] = Field(description="Functional requirements such as mounting features, interfaces, etc.")
        environmental_thermal: List[str] = Field(description="Environmental and thermal requirements (e.g. IP rating, temperature limits, weatherability)")
        structural: List[str] = Field(description="Structural/load limits and reinforcement needs")
        manufacturing_cost: List[str] = Field(description="Manufacturing constraints (e.g., sheet metal vs. injection molding) and cost targets")

    class ClarificationPair(BaseModel):
        question: str = Field(description="The clarifying question asked by the agent using ask_user")
        answer: str = Field(description="The answer supplied by the user")

    title: str = Field(description="Short descriptive title of the design project")
    overall_dimensions: OverallDimensions = Field(description="Overall bounding box dimensions of the complete assembly")
    assembly_kind: Literal["single_solid", "assembly"] = Field(default="single_solid", description="single_solid = one fused, connected manufacturable body (parts must touch); assembly = several distinct parts that stay separate (each verified on its own). Use 'assembly' when the object is genuinely multiple pieces (e.g. a bolt sitting in a bracket).")
    engineering_requirements: EngineeringRequirements = Field(description="Engineering specification extracted and parsed from the prompt and Q&A")
    assumptions: List[str] = Field(description="A list of assumed default values or decisions made for under-specified parameters")
    clarifications: List[ClarificationPair] = Field(default_factory=list, description="Log of clarifying questions asked to the user and their replies using the ask_user tool.")
    primitives_sequence: List[PrimitiveStep] = Field(description="Step-by-step sequence of CAD steps representing the build order. Use primitive steps where a primitive fits; use a 'custom' freeform CadQuery step where no primitive can represent the shape.")
    contains_freeform: bool = Field(default=False, description="Auto-set: True if any step is a freeform 'custom' step, meaning the plan ships at trust tier needs_review.")

    @model_validator(mode="after")
    def _flag_freeform(self) -> "GeometryPlan":
        self.contains_freeform = any(
            getattr(s, "primitive_type", None) == "custom" for s in self.primitives_sequence
        )
        return self

    @model_validator(mode="after")
    def _validate_step_sequence(self) -> "GeometryPlan":
        steps = self.primitives_sequence
        if not steps:
            raise ValueError("GeometryPlan must contain at least one step in primitives_sequence.")
        
        sequence_ids = [s.sequence_id for s in steps]
        if sequence_ids[0] != 1:
            raise ValueError(f"Step sequence must start with sequence_id 1 (found {sequence_ids[0]}).")
        
        for idx, seq_id in enumerate(sequence_ids):
            expected = idx + 1
            if seq_id != expected:
                raise ValueError(
                    f"Step sequence is non-sequential or contains duplicate IDs. "
                    f"Expected step at index {idx} to have sequence_id {expected}, but found {seq_id}."
                )
        return self

    @model_validator(mode="after")
    def _validate_rationales(self) -> "GeometryPlan":
        steps = self.primitives_sequence
        rationales = []
        for s in steps:
            rat = s.rationale.strip()
            if len(rat) < 15:
                raise ValueError(
                    f"Step {s.sequence_id}'s rationale is too short ({len(rat)} chars). "
                    "Please provide a meaningful explanation of at least 15 characters describing "
                    "how this step addresses the requirements."
                )
            rationales.append(rat)
        return self

    @model_validator(mode="after")
    def _validate_primitive_parameters(self) -> "GeometryPlan":
        for s in self.primitives_sequence:
            p_type = s.primitive_type
            if p_type == "custom":
                continue
                
            params = s.parameters
            if p_type in ("hollow_cylinder", "ring"):
                inner = getattr(params, "inner_radius", None)
                outer = getattr(params, "outer_radius", None)
                if inner is not None and outer is not None and inner >= outer:
                    raise ValueError(f"inner_radius ({inner}) must be strictly less than outer_radius ({outer}) for step {s.sequence_id}.")
                    
            elif p_type == "hollow_box":
                wt = getattr(params, "wall_thickness", None)
                l = getattr(params, "length", None)
                w = getattr(params, "width", None)
                h = getattr(params, "height", None)
                if wt is not None:
                    if l is not None and wt * 2 >= l:
                        raise ValueError(f"wall_thickness ({wt}) must be less than half of length ({l}) for hollow box step {s.sequence_id}.")
                    if w is not None and wt * 2 >= w:
                        raise ValueError(f"wall_thickness ({wt}) must be less than half of width ({w}) for hollow box step {s.sequence_id}.")
                    if h is not None and wt >= h:
                        raise ValueError(f"wall_thickness ({wt}) must be less than height ({h}) for hollow box step {s.sequence_id}.")
                        
            elif p_type in ("chamfered_box", "filleted_box"):
                val = getattr(params, "chamfer_val", getattr(params, "fillet_val", None))
                l = getattr(params, "length", None)
                w = getattr(params, "width", None)
                h = getattr(params, "height", None)
                if val is not None and l is not None and w is not None and h is not None:
                    max_allowed = min(l, w, h) / 2
                    if val >= max_allowed:
                        raise ValueError(
                            f"{'chamfer_val' if p_type == 'chamfered_box' else 'fillet_val'} ({val}) must be strictly less than half of the minimum dimension "
                            f"({max_allowed * 2}) to prevent self-intersecting fillets/chamfers in step {s.sequence_id}."
                        )
                        
            elif p_type == "rounded_cylinder":
                val = getattr(params, "fillet_val", None)
                r = getattr(params, "radius", None)
                h = getattr(params, "height", None)
                if val is not None and r is not None and h is not None:
                    if val >= r or val >= h:
                        raise ValueError(
                            f"fillet_val ({val}) must be strictly less than both radius ({r}) and height ({h}) "
                            f"to prevent self-intersecting fillets in step {s.sequence_id}."
                        )
        return self

