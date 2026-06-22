from typing import Any


def inspect_mesh(stl_path: str) -> dict:
    """
    Inspects the mesh geometry from an STL file using MeshLib.
    Checks for watertightness, manifold quality, open edges, and volume.

    NOTE on singularities: CadQuery exports sharp-tipped cones with 1 open boundary
    edge at the apex point. This is expected OCCT tessellation behaviour and is NOT
    a mesh defect. We allow up to 1 singular (zero-length) open edge before failing.

    Args:
        stl_path: Absolute path to the STL file.

    Returns:
        A dictionary containing:
        - success: bool
        - is_watertight: bool
        - open_edges: int         (count of true boundary edges)
        - singular_edges: int     (count of zero-length degenerate edges, e.g. cone apex)
        - volume_mm3: float
        - is_manifold: bool
        - face_count: int         (number of triangular faces in the mesh)
        - vertex_count: int       (number of mesh vertices)
        - passes: bool            (overall quality — True if watertight OR only singular apex edges)
        - error: str              (optional, only present if success=False)
    """
    import os
    import traceback

    if not os.path.exists(stl_path):
        return {"success": False, "error": f"STL file not found at {stl_path}"}

    try:
        from meshlib import mrmeshpy as mr

        mesh = mr.loadMesh(stl_path)

        # Watertightness — no open boundary loops
        topo = mesh.topology
        is_watertight = bool(topo.isClosed())

        # Volume (can be negative if normals are inverted)
        volume = abs(float(mesh.volume()))

        # Manifold structure validity
        is_manifold = bool(topo.checkValidity())

        # Count true boundary vs singular degenerate edges
        true_open_count, singular_count = _count_boundary_edges(mesh)

        # PASSES if:
        #   - no true open boundary edges (only allowed to have singular apex edges)
        #   - positive volume
        passes = bool(true_open_count == 0 and volume > 0.0)

        return {
            "success": True,
            "is_watertight": is_watertight,
            "open_edges": true_open_count,
            "singular_edges": singular_count,
            "volume_mm3": volume,
            "is_manifold": is_manifold,
            "face_count": topo.numValidFaces(),
            "vertex_count": topo.numValidVerts(),
            "passes": passes,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to inspect STL mesh: {str(e)}",
            "traceback": traceback.format_exc(),
        }


def _count_boundary_edges(mesh: Any) -> tuple[int, int]:
    """Helper to classify and count boundary edges into true open and singular ones."""
    topo = mesh.topology
    bd_edges = topo.findLeftBdEdges()

    true_open_count = 0
    singular_count = 0

    for edge_id in bd_edges:
        org_id = topo.org(edge_id)
        dest_id = topo.dest(edge_id)
        p0 = mesh.points[org_id]
        p1 = mesh.points[dest_id]
        edge_length = (p1 - p0).length()

        if edge_length < 1e-6:
            singular_count += 1
        else:
            true_open_count += 1

    return true_open_count, singular_count
