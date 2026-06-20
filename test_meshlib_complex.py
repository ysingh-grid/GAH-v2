import sys

from tools import execute_cadquery, inspect_mesh
from tools.artifacts import new_run_id

print("🚀 Running Advanced MeshLib Verification Test...")

# =====================================================================
# TEST CASE 1: Valid Complex Mounting Bracket (Should Pass)
# =====================================================================
print("\n" + "=" * 60)
print("TEST CASE 1: Complex Watertight Mounting Bracket")
print("=" * 60)

run_id_1 = new_run_id("bracket_test")
code_1 = """import cadquery as cq
# 80x40x10mm plate
bracket = cq.Workplane("XY").box(80, 40, 10)
# Fillet vertical edges
bracket = bracket.edges("|Z").fillet(5)
# Add 4 corner holes
bracket = bracket.faces(">Z").workplane().rect(70, 30, forConstruction=True).vertices().hole(5)
# Add central slot
result = bracket.faces(">Z").workplane().slot2D(40, 15).cutThruAll()
"""

ex_1 = execute_cadquery(code_1, run_id_1)
if not ex_1.get("success"):
    print("❌ Part 1 CadQuery compilation failed:", ex_1.get("error"))
    sys.exit(1)

mesh_1 = inspect_mesh(ex_1["stl_path"])
if not mesh_1.get("success"):
    print("❌ Part 1 MeshLib inspection failed:", mesh_1.get("error"))
    sys.exit(1)

print(f"  Watertight: {mesh_1['is_watertight']} (Expected: True)")
print(f"  Open Edges: {mesh_1['open_edges']} (Expected: 0)")
print(f"  Volume: {mesh_1['volume_mm3']:.2f} mm3")
print(f"  Is Manifold: {mesh_1['is_manifold']} (Expected: True)")
print(f"  Passes Quality Gate: {mesh_1['passes']} (Expected: True)")

# =====================================================================
# TEST CASE 2: Invalid Open Surface Sheet (Should Fail)
# =====================================================================
print("\n" + "=" * 60)
print("TEST CASE 2: Open Sheet (Non-Watertight)")
print("=" * 60)

run_id_2 = new_run_id("sheet_test")
code_2 = """import cadquery as cq
# Generate a flat 2D rectangle face (zero thickness, open boundaries)
result = cq.Face.makePlane(20, 20)
"""

ex_2 = execute_cadquery(code_2, run_id_2)
if not ex_2.get("success"):
    print("❌ Part 2 CadQuery compilation failed:", ex_2.get("error"))
    sys.exit(1)

mesh_2 = inspect_mesh(ex_2["stl_path"])
if not mesh_2.get("success"):
    print("❌ Part 2 MeshLib inspection failed:", mesh_2.get("error"))
    sys.exit(1)

print(f"  Watertight: {mesh_2['is_watertight']} (Expected: False)")
print(f"  Open Edges: {mesh_2['open_edges']} (Expected: > 0)")
print(f"  Volume: {mesh_2['volume_mm3']:.2f} mm3 (Expected: ~0)")
print(f"  Is Manifold: {mesh_2['is_manifold']}")
print(f"  Passes Quality Gate: {mesh_2['passes']} (Expected: False)")

# =====================================================================
# Verification Verdict
# =====================================================================
print("\n" + "=" * 60)
if mesh_1["passes"] and not mesh_2["passes"]:
    print(
        "✅ VERDICT: MeshLib is working perfectly! It correctly verified the complex watertight bracket and rejected the open sheet."
    )
else:
    print("❌ VERDICT: MeshLib verification failed to distinguish watertight vs open meshes.")
print("=" * 60)
