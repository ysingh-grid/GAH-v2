"""Runtime-appended store of user-APPROVED generated designs — the trace flywheel.

Curated recipes live in backend/design_reference (hand-edited, source-controlled).
This store is the MACHINE-written counterpart: each entry is a past generation a
user confirmed correct. Entries surface to the planner/replanner through the SAME
design-reference index/fetch surface, so a proven past design can be retrieved by
key and adapted like any recipe.
"""
