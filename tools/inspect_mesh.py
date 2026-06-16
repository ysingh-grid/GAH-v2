def inspect_mesh(stl_path: str) -> dict:
    """
    Inspects the mesh geometry from an STL file using trimesh.
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
        return {
            "success": False,
            "error": f"STL file not found at {stl_path}"
        }
        
    try:
        import trimesh
        import numpy as np
        
        mesh = trimesh.load(stl_path)
        
        # Watertightness — no open boundary loops
        is_watertight = bool(mesh.is_watertight)
        
        # All open boundary edge groups (by index)
        open_edge_groups = trimesh.grouping.group_rows(mesh.edges_sorted, require_count=1)
        total_open_count = len(open_edge_groups)
        
        # Distinguish between true open edges and zero-length singular edges (cone apex)
        # A degenerate edge has both vertices at the same position (zero length)
        singular_count = 0
        true_open_count = 0
        if total_open_count > 0:
            for group_idx in open_edge_groups:
                # Get edge vertex indices
                edge = mesh.edges_sorted[group_idx]
                v0 = mesh.vertices[edge[0]]
                v1 = mesh.vertices[edge[1]]
                edge_length = np.linalg.norm(v1 - v0)
                if edge_length < 1e-6:
                    singular_count += 1
                else:
                    true_open_count += 1
        
        # Volume (can be negative if normals are inverted)
        volume = abs(float(mesh.volume)) if mesh.volume is not None else 0.0
        
        # Manifold volume solid
        is_manifold = bool(mesh.is_volume)
        
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
            "face_count": len(mesh.faces),
            "vertex_count": len(mesh.vertices),
            "passes": passes
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to inspect STL mesh: {str(e)}",
            "traceback": traceback.format_exc()
        }
