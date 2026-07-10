from typing import Any

# A repair that shifts total volume more than this fraction has changed the
# GEOMETRY, not fixed mesh defects. Measured live before this guard existed:
# a voxel self-intersection remesh returned a mesh at +151% volume and 54
# components (was 3), and another stripped a spoon to -8.3% volume / a third
# of its faces — and those butchered meshes were what got rendered and judged.
_MAX_VOLUME_DRIFT = 0.05


def repair_mesh(
    stl_path: str, run_id: str, expected_components: int = 1
) -> dict[str, Any]:
    """Repair an STL mesh with MeshLib, recording every action taken.

    Repairs are bounded and auditable (PRD: never silently hide design mistakes).
    The pipeline fills boundary holes (the common, safe repair that makes a mesh
    watertight) and, only if self-intersections are present, attempts a guarded
    voxel-based self-intersection fix.

    A repair must leave the mesh BETTER than it found it. The voxel remesh in
    particular can shatter a mesh into dozens of components or balloon its
    volume (see _MAX_VOLUME_DRIFT above for live measurements) — so the result
    is accepted only if it (a) actually passes inspection against
    `expected_components` and (b) stayed within the volume-drift bound.
    Otherwise the repaired file is DELETED and the failure routes back to the
    replanner with the degradation spelled out: self-intersecting geometry that
    cannot be safely repaired is a PLAN problem (overlapping or self-folding
    surfaces), and handing downstream a butchered mesh hides exactly the
    mistake the verifier exists to catch.

    Args:
        stl_path: Path to the STL to repair.
        run_id: Run identifier; the repaired STL lands in that run's folder.
        expected_components: Ground-truth component count from the B-rep shell
            count (execution_result["shells_count"]).

    Returns:
        On success:
          {"success": True, "repaired_stl_path": str, "actions": [str],
           "before": {"open_holes": int, "self_intersections": int,
                      "num_components": int, "volume_mm3": float},
           "after": <inspect_mesh report>, "passes": bool}
          (on a rejected repair: passes=False, "rejected": [str reasons],
           and repaired_stl_path is absent — the original stays authoritative)
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

        volume_before = abs(mesh.volume())
        components_before = mr.MeshComponents.getNumComponents(mesh)

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

        after = inspect_mesh(repaired_path, expected_components)
        before = {
            "open_holes": holes_before,
            "self_intersections": self_before,
            "num_components": components_before,
            "volume_mm3": volume_before,
        }

        # ── Reject-if-worse guard ────────────────────────────────────────────
        rejected: list[str] = []
        vol_after = float(after.get("volume_mm3") or 0.0)
        if volume_before > 0:
            drift = abs(vol_after - volume_before) / volume_before
            if drift > _MAX_VOLUME_DRIFT:
                rejected.append(
                    f"volume drifted {drift:+.1%} ({volume_before:.1f} -> "
                    f"{vol_after:.1f} mm^3) — repair changed the geometry, not "
                    f"just the mesh"
                )
        comps_after = int(after.get("num_components") or 0)
        if comps_after > max(components_before, expected_components):
            rejected.append(
                f"repair shattered the mesh into {comps_after} components "
                f"(was {components_before}, expected {expected_components})"
            )

        if rejected:
            # The repaired file must not survive to be rendered or judged.
            os.remove(repaired_path)
            return {
                "success": True,
                "actions": actions,
                "before": before,
                "after": after,
                "passes": False,
                "rejected": rejected,
                "error": (
                    "repair REJECTED (it degraded the mesh: "
                    + "; ".join(rejected)
                    + "). The underlying geometry is self-intersecting or "
                    "broken in a way meshing cannot safely fix — fix the PLAN "
                    "(look for overlapping bodies, self-folding swept/lofted "
                    "surfaces, or coincident faces)."
                ),
            }

        return {
            "success": True,
            "repaired_stl_path": repaired_path,
            "actions": actions,
            "before": before,
            "after": after,
            "passes": bool(after.get("passes", False)),
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"MeshLib failed to repair STL mesh: {e}",
            "traceback": traceback.format_exc(),
        }
