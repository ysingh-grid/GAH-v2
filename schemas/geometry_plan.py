from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any

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

    class PrimitiveStep(BaseModel):
        sequence_id: int = Field(description="Sequence step number starting from 1")
        primitive_type: str = Field(description="Type of primitive, e.g., enclosure, mounting_plate, mounting_boss, hole, rib, bracket, fillet, cooling_fin, sealing_interface")
        parameters: Dict[str, Any] = Field(description="Specific parameters for this primitive (coordinates, dimensions, thickness, diameter, count, etc.)")
        rationale: str = Field(description="Short explanation of how this primitive addresses a specific engineering requirement")

    title: str = Field(description="Short descriptive title of the design project")
    overall_dimensions: OverallDimensions = Field(description="Overall bounding box dimensions of the complete assembly")
    engineering_requirements: EngineeringRequirements = Field(description="Engineering specification extracted and parsed from the prompt and Q&A")
    assumptions: List[str] = Field(description="A list of assumed default values or decisions made for under-specified parameters")
    clarifications: List[ClarificationPair] = Field(min_length=1, description="Log of clarifying questions asked to the user and their replies. You must ask at least one question using the host MCP tool ask_user.")
    primitives_sequence: List[PrimitiveStep] = Field(description="Step-by-step sequence of CAD primitive operations representing the build order")
