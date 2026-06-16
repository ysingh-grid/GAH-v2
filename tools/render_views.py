def render_views(stl_path: str, run_id: str) -> dict:
    """
    Renders three PNG views (front, top, isometric) of an STL model.
    Uses matplotlib for a server-side render without GUI dependencies.
    
    Args:
        stl_path: Absolute path to the STL file.
        run_id: A unique identifier for the run.
        
    Returns:
        A dictionary containing:
        - success: bool
        - renders: dict with paths to 'front', 'top', and 'iso' PNGs.
        - error: str (optional, if success=False)
    """
    import os
    import traceback
    
    # Path setup
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    outputs_dir = os.path.join(base_dir, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)
    
    front_path = os.path.join(outputs_dir, f"{run_id}_front.png")
    top_path = os.path.join(outputs_dir, f"{run_id}_top.png")
    iso_path = os.path.join(outputs_dir, f"{run_id}_iso.png")
    
    if not os.path.exists(stl_path):
        return {
            "success": False,
            "error": f"STL file not found at {stl_path}"
        }
        
    try:
        import trimesh
        import matplotlib
        # Use Agg backend for non-GUI headless plotting
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        
        # Load mesh
        mesh = trimesh.load(stl_path)
        
        # Extract triangles (faces x 3 vertices x 3 coordinates)
        triangles = mesh.triangles
        
        # Setup views
        views = {
            "front": {"elev": 0, "azim": -90, "path": front_path},
            "top": {"elev": 90, "azim": -90, "path": top_path},
            "iso": {"elev": 30, "azim": 45, "path": iso_path}
        }
        
        # Preserve original aspect ratios of the bounding box
        bounds = mesh.bounds
        max_range = max(bounds[1] - bounds[0])
        mid_x = (bounds[1][0] + bounds[0][0]) / 2.0
        mid_y = (bounds[1][1] + bounds[0][1]) / 2.0
        mid_z = (bounds[1][2] + bounds[0][2]) / 2.0
        
        render_paths = {}
        
        for name, view_opt in views.items():
            fig = plt.figure(figsize=(6, 6), facecolor='#0d1b2a')
            ax = fig.add_subplot(projection='3d')
            ax.set_facecolor('#0d1b2a')
            
            # Create a 3D polygon collection with premium dark cyan aesthetic
            poly = Poly3DCollection(
                triangles, 
                facecolors='#2b78e4', 
                edgecolors='#00e5ff', 
                linewidths=0.1, 
                alpha=0.85
            )
            
            ax.add_collection3d(poly)
            
            # Set uniform limits to prevent distortion
            ax.set_xlim(mid_x - max_range/2.0, mid_x + max_range/2.0)
            ax.set_ylim(mid_y - max_range/2.0, mid_y + max_range/2.0)
            ax.set_zlim(mid_z - max_range/2.0, mid_z + max_range/2.0)
            
            # Hide grid, axes lines and labels for studio rendering look
            ax.grid(False)
            ax.set_axis_off()
            
            # Set camera position
            ax.view_init(elev=view_opt["elev"], azim=view_opt["azim"])
            
            # Save the figure
            plt.savefig(
                view_opt["path"], 
                dpi=150, 
                bbox_inches='tight', 
                pad_inches=0.1, 
                facecolor=fig.get_facecolor(), 
                edgecolor='none'
            )
            plt.close(fig)
            
            render_paths[name] = view_opt["path"]
            
        return {
            "success": True,
            "renders": render_paths
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to render STL views: {str(e)}",
            "traceback": traceback.format_exc()
        }
