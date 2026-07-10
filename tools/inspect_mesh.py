from typing import Any


def inspect_mesh(stl_path: str, expected_components: int = 1) -> dict[str, Any]:
    """Inspect an STL mesh with MeshLib (the canonical mesh authority).

    Reports watertightness (boundary holes), self-intersections, connected
    components, volume, bounding box, and face/vertex counts. A mesh "passes"
    when it is watertight, has no self-intersections, and its component count
    matches `expected_components` — the geometric-validity gate before visual
    verification.

    `expected_components` is the B-rep shell count reported by the executor
    (execution_result["shells_count"]): one closed shell tessellates to exactly
    one mesh component, so a plain solid expects 1, a legal multi-body compound
    expects N, and a closed hollow part expects 2 (outer + cavity). The old
    hardcoded ==1 gate wrongly failed every legal multi-body plan (measured: a
    valid watertight two-box compound could never pass, repair found nothing to
    fix, and the run burned its replan budget on a correct model).

    MeshLib is the only backend (no trimesh fallback, per design): a MeshLib
    load/inspect failure returns success=False so the loop routes it back to the
    RLM as a mesh failure rather than silently degrading.

    Args:
        stl_path: Path to the STL file.
        expected_components: How many connected components the mesh SHOULD
            have (from the B-rep shell count). Defaults to 1.

    Returns:
        On success:
          {"success": True, "is_watertight": bool, "open_holes": int,
           "self_intersections": int, "num_components": int,
           "expected_components": int, "passes": bool,
           "volume_mm3": float, "faces_count": int, "vertex_count": int,
           "bbox": {"xmin"..."zmax"}}
        On failure:
          {"success": False, "error": str, "traceback": str}
    """
    import os
    import traceback

    if not os.path.exists(stl_path):
        return {"success": False, "error": f"STL file not found at {stl_path}"}

    try:
        import meshlib.mrmeshpy as mr

        mesh = mr.loadMesh(stl_path)
        topology = mesh.topology

        open_holes = len(topology.findHoleRepresentiveEdges())
        is_watertight = open_holes == 0
        self_intersections = len(mr.findSelfCollidingTriangles(mesh))
        num_components = mr.MeshComponents.getNumComponents(mesh)

        box = mesh.computeBoundingBox()
        bbox = {
            "xmin": box.min.x,
            "ymin": box.min.y,
            "zmin": box.min.z,
            "xmax": box.max.x,
            "ymax": box.max.y,
            "zmax": box.max.z,
        }

        passes = (
            is_watertight
            and self_intersections == 0
            and num_components == expected_components
        )

        return {
            "success": True,
            "is_watertight": is_watertight,
            "open_holes": open_holes,
            "self_intersections": self_intersections,
            "num_components": num_components,
            "expected_components": expected_components,
            "passes": passes,
            "volume_mm3": abs(mesh.volume()),
            "faces_count": topology.numValidFaces(),
            "vertex_count": topology.numValidVerts(),
            "bbox": bbox,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"MeshLib failed to inspect STL mesh: {e}",
            "traceback": traceback.format_exc(),
        }
