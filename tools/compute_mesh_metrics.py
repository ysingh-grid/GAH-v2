"""tools/compute_mesh_metrics.py
===================================
Geometry quality metrics: Chamfer Distance, F1 Score, Volumetric IoU.

Compares a generated STL against a reference STL to measure how close the
geometry is to the ground truth. Used by the eval harness (eval/benchmark.py)
to score each design attempt.

MeshLib is the only backend — consistent with inspect_mesh.py and repair_mesh.py.

Algorithm
---------
Chamfer Distance (CD):
    Mean of two one-way average distances:
      - gen→ref: for each vertex in the generated mesh, the distance to its
                  nearest point on the reference mesh surface.
      - ref→gen: symmetric.
    CD = (mean(gen→ref) + mean(ref→gen)) / 2

F1 Score:
    Precision = fraction of generated vertices within `threshold` mm of ref.
    Recall    = fraction of reference vertices within `threshold` mm of gen.
    F1        = 2 * P * R / (P + R)
    Default threshold = 1.0 mm (matches the CADSmith baseline eval protocol).

Volumetric IoU (proxy):
    min(vol_gen, vol_ref) / max(vol_gen, vol_ref)
    Exact voxel-based IoU requires an expensive voxelisation step; this volume
    ratio is a reliable proxy for convex and near-convex primitives.

ICP Alignment (optional, default=True):
    Before computing distances, aligns the generated mesh to the reference using
    MeshLib's ICP. This corrects for any centring / origin differences between
    the agent's output and the reference STL without changing the shape itself.
"""

from __future__ import annotations

import traceback
from typing import Any


def compute_mesh_metrics(
    *,
    generated_stl_path: str,
    reference_stl_path: str,
    f1_threshold_mm: float = 1.0,
    use_icp: bool = True,
) -> dict[str, Any] | None:
    """Compare a generated STL against a reference STL using MeshLib.

    Args:
        generated_stl_path: Absolute path to the generated STL file.
        reference_stl_path: Absolute path to the reference (ground-truth) STL.
        f1_threshold_mm: Distance threshold in mm for F1 precision/recall.
        use_icp: If True, align generated mesh to reference before measuring.

    Returns:
        On success:
            {
                "chamfer_distance": float,   # mean mm, lower is better
                "f1_score": float,           # 0-1, higher is better
                "volumetric_iou": float,     # 0-1, higher is better
                "precision": float,
                "recall": float,
                "volume_gen_mm3": float,
                "volume_ref_mm3": float,
                "n_verts_gen": int,
                "n_verts_ref": int,
                "icp_applied": bool,
            }
        On failure (bad STL, MeshLib error, zero-vertex mesh):
            None
    """
    import os

    if not os.path.exists(generated_stl_path):
        return None
    if not os.path.exists(reference_stl_path):
        return None

    try:
        return _compute_metrics_with_meshlib(
            generated_stl_path=generated_stl_path,
            reference_stl_path=reference_stl_path,
            f1_threshold_mm=f1_threshold_mm,
            use_icp=use_icp,
        )
    except Exception:
        # Never crash the eval loop — caller decides what to do with None.
        traceback.print_exc()
        return None


# ---------------------------------------------------------------------------
# Internal implementation — kept private so the public signature stays clean.
# ---------------------------------------------------------------------------


def _compute_metrics_with_meshlib(
    *,
    generated_stl_path: str,
    reference_stl_path: str,
    f1_threshold_mm: float,
    use_icp: bool,
) -> dict[str, Any] | None:
    """Core MeshLib implementation. Raises on any error (caller wraps in try/except)."""
    import meshlib.mrmeshpy as mr

    mesh_gen = mr.loadMesh(generated_stl_path)
    mesh_ref = mr.loadMesh(reference_stl_path)

    n_verts_gen = mesh_gen.topology.numValidVerts()
    n_verts_ref = mesh_ref.topology.numValidVerts()

    if n_verts_gen == 0 or n_verts_ref == 0:
        return None  # degenerate mesh — skip rather than compute nonsense

    # Optionally align generated mesh to reference via ICP.
    # ICP mutates the transform of the floating mesh (mesh_gen) to best match
    # mesh_ref without changing the shape. We then use the aligned positions
    # when computing distances.
    icp_applied = False
    xf_gen = mr.AffineXf3f()   # identity — start unaligned
    xf_ref = mr.AffineXf3f()   # reference stays fixed

    if use_icp:
        # samplingVoxelSize ≈ 5% of the bounding-box diagonal gives ~400 samples
        # on a typical T1 primitive: fast and accurate enough.
        box = mesh_ref.computeBoundingBox()
        diagonal = (box.max - box.min).length()
        sampling_voxel_size = max(diagonal * 0.05, 0.5)

        icp = mr.ICP(
            mr.MeshOrPoints(mesh_gen),
            mr.MeshOrPoints(mesh_ref),
            xf_gen,
            xf_ref,
            sampling_voxel_size,
        )
        props = mr.ICPProperties()
        props.exitVal = 1e-4   # stop when RMS improvement < 0.1 µm
        icp.setParams(props)

        xf_gen = icp.calculateTransformation()
        icp_applied = True

    # Compute one-way signed distances (we use absolute values for CD/F1).
    # findSignedDistances(ref, test, xfTest?) isn't available with a transform
    # parameter directly, so we apply the ICP transform to the generated mesh's
    # point coordinates before querying.
    d_gen_to_ref = _vertex_distances_to_mesh(mesh_gen, mesh_ref, xf_source=xf_gen)
    d_ref_to_gen = _vertex_distances_to_mesh(mesh_ref, mesh_gen, xf_source=xf_ref)

    if d_gen_to_ref is None or d_ref_to_gen is None:
        return None

    import numpy as np

    d_g2r = np.asarray(d_gen_to_ref, dtype=float)
    d_r2g = np.asarray(d_ref_to_gen, dtype=float)

    chamfer_distance = float((d_g2r.mean() + d_r2g.mean()) / 2.0)

    precision = float(np.mean(d_g2r <= f1_threshold_mm))
    recall    = float(np.mean(d_r2g <= f1_threshold_mm))
    denom = precision + recall
    f1_score = float(2.0 * precision * recall / denom) if denom > 0 else 0.0

    vol_gen = abs(float(mesh_gen.volume()))
    vol_ref = abs(float(mesh_ref.volume()))
    iou_proxy = (
        min(vol_gen, vol_ref) / max(vol_gen, vol_ref)
        if max(vol_gen, vol_ref) > 0
        else 0.0
    )

    return {
        "chamfer_distance": chamfer_distance,
        "f1_score": f1_score,
        "volumetric_iou": iou_proxy,
        "precision": precision,
        "recall": recall,
        "volume_gen_mm3": vol_gen,
        "volume_ref_mm3": vol_ref,
        "n_verts_gen": n_verts_gen,
        "n_verts_ref": n_verts_ref,
        "icp_applied": icp_applied,
    }


def _vertex_distances_to_mesh(
    source_mesh,
    target_mesh,
    xf_source,
) -> list[float] | None:
    """Return absolute per-vertex distances from source_mesh vertices to target_mesh surface.

    Applies xf_source to the source vertices before projecting so ICP alignment
    is taken into account without modifying the mesh object itself.

    Args:
        source_mesh: The mesh whose vertices are the query points.
        target_mesh: The mesh whose surface we project onto.
        xf_source:   AffineXf3f transform to apply to source vertices first.

    Returns:
        List of non-negative distances (one per valid source vertex), or None on error.
    """
    import meshlib.mrmeshpy as mr

    n = source_mesh.topology.numValidVerts()
    if n == 0:
        return None

    # Transform source vertices into target-mesh space.
    # mr.AffineXf3f is identity when constructed with no args.
    is_identity = _is_identity_xf(xf_source)

    if is_identity:
        # Fast path: no transform needed, query directly.
        vert_scalars = mr.findSignedDistances(target_mesh, source_mesh)
    else:
        # Apply ICP transform to get aligned vertex coordinates, then query.
        # We build a temporary VertCoords of the transformed positions.
        transformed_coords = mr.VertCoords()
        transformed_coords.resize(n)
        for i in range(n):
            vid = mr.VertId(i)
            original_pt = source_mesh.points[vid]
            transformed_coords[vid] = xf_source(original_pt)
        valid_verts = source_mesh.topology.getValidVerts()
        vert_scalars = mr.findSignedDistances(target_mesh, transformed_coords, valid_verts)

    return [abs(float(vert_scalars[mr.VertId(i)])) for i in range(n)]


def _is_identity_xf(xf) -> bool:
    """Return True if the AffineXf3f is approximately the identity transform.

    Checks both the translation vector (.b) and the linear matrix (.A).
    ICP can produce a pure rotation with zero translation, which would pass a
    translation-only check but is not identity.
    """
    # Translation must be near-zero.
    t = xf.b
    if abs(t.x) > 1e-6 or abs(t.y) > 1e-6 or abs(t.z) > 1e-6:
        return False

    # Linear matrix must be near the 3×3 identity.
    # AffineXf3f.A is a Matrix3f with rows x, y, z (each a Vector3f).
    # Identity rows: (1,0,0), (0,1,0), (0,0,1).
    a = xf.A
    row_x, row_y, row_z = a.x, a.y, a.z
    identity_rows = [
        (row_x.x - 1.0, row_x.y, row_x.z),
        (row_y.x, row_y.y - 1.0, row_y.z),
        (row_z.x, row_z.y, row_z.z - 1.0),
    ]
    return all(
        abs(v) < 1e-6
        for row in identity_rows
        for v in row
    )
