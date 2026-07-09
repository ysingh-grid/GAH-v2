"""Read-only service exposing standards-aware dims + adaptable CSG recipes.

Backs the planner's design-reference index/fetch pull tools so the RLM can ground
its plans in standard fastener dimensions, known-good recipe templates, and past
USER-APPROVED designs (merged from backend/approved_store) instead of inventing
geometry blind. Door onto primitives/design_reference.json + the approved store.
"""
