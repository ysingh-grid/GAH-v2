"""Read-only service exposing standards-aware dims + adaptable CSG recipes.

Backs the planner's `lookup_design_reference` pull tool so the RLM can ground its
plans in standard fastener dimensions and known-good recipe templates instead of
inventing geometry blind. Read-only door onto primitives/design_reference.json.
"""
