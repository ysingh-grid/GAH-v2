from typing import Any


def repair_mesh(stl_path: str, run_id: str) -> dict[str, Any]:
    """Repair an STL mesh with MeshLib, recording every action taken.

    Repairs are bounded and auditable (PRD: never silently hide design mistakes).
    The pipeline fills boundary holes (the common, safe repair that makes a mesh
    watertight) and, only if self-intersections are present, attempts a guarded
    voxel-based self-intersection fix. Every change is listed in `actions` and
    the before/after inspection is returned so the caller can judge whether the
    repair was cosmetic or structural.

    A repaired STL is written next to the run's other artifacts as
    `solid_repaired.stl`. If MeshLib cannot repair the mesh, success=False and
    the failure routes back to the RLM as a `mesh_repair` failure (no fallback).

    Args:
        stl_path: Path to the STL to repair.
        run_id: Run identifier; the repaired STL lands in that run's folder.

    Returns:
        On success:
          {"success": True, "repaired_stl_path": str, "actions": [str],
           "before": {"open_holes": int, "self_intersections": int},
           "after": <inspect_mesh report>, "passes": bool}
        On failure:
          {"success": False, "error": str, "traceback": str}
    """
    import os
    import traceback

    if not os.path.exists(stl_path):
        return {"success": False, "error": f"STL file not found at {stl_path}"}

    try:
        import meshlib.mrmeshpy as mr

        from .artifacts import run_dir
        from .inspect_mesh import inspect_mesh

        mesh = mr.loadMesh(stl_path)
        actions: list[str] = []

        # 1) Fill every boundary hole (makes the mesh watertight).
        hole_edges = mesh.topology.findHoleRepresentiveEdges()
        holes_before = len(hole_edges)
        for edge in hole_edges:
            mr.fillHole(mesh, edge)
        if holes_before:
            actions.append(f"filled {holes_before} boundary hole(s)")

        # 2) Fix self-intersections only if present (voxel remesh is structural).
        self_before = len(mr.findSelfCollidingTriangles(mesh))
        if self_before:
            box = mesh.computeBoundingBox()
            diagonal = (box.max - box.min).length()
            voxel_size = max(diagonal / 200.0, 1e-4)
            try:
                mr.fixSelfIntersections(mesh, voxel_size)
                actions.append(
                    f"fixed self-intersections via voxel remesh (voxel={voxel_size:.4g})"
                )
            except Exception as exc:  # noqa: BLE001 — report, don't abort the repair
                actions.append(f"self-intersection fix skipped: {exc}")

        if not actions:
            actions.append("no repair needed (already clean)")

        repaired_path = os.path.join(str(run_dir(run_id)), "solid_repaired.stl")
        mr.saveMesh(mesh, repaired_path)

        after = inspect_mesh(repaired_path)
        return {
            "success": True,
            "repaired_stl_path": repaired_path,
            "actions": actions,
            "before": {"open_holes": holes_before, "self_intersections": self_before},
            "after": after,
            "passes": bool(after.get("passes", False)),
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"MeshLib failed to repair STL mesh: {e}",
            "traceback": traceback.format_exc(),
        }
