def render_views(stl_path: str, run_id: str) -> dict:
    """
    Renders a single composite PNG with THREE side-by-side views of an STL,
    using VTK with Phong shading (server-side, offscreen, no GUI).

    Views (left -> right):
      - Isometric        (elev=35,  azim=45)  — overall 3D shape
      - High-angle rear  (elev=65,  azim=220) — top-face holes/bores/cavities
      - Low front profile(elev=10,  azim=0)   — vertical profile, heights, slots

    Args:
        stl_path: Absolute (or repo-relative) path to the STL file.
        run_id: Unique identifier for the run; names the output PNG.

    Returns:
        On success:
          {"success": True, "png_path": str, "width": int, "height": int,
           "views": ["iso", "high_rear", "front"],
           "renders": {"composite": png_path}}
        On failure:
          {"success": False, "error": str}
    """
    import os
    import traceback

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    outputs_dir = os.path.join(base_dir, "outputs")
    os.makedirs(outputs_dir, exist_ok=True)
    out_png = os.path.join(outputs_dir, f"{run_id}_threeview.png")

    if not os.path.exists(stl_path):
        return {"success": False, "error": f"STL file not found at {stl_path}"}

    try:
        import numpy as np
        import vtk

        size = (2400, 800)
        scale = 2

        # Read STL
        reader = vtk.vtkSTLReader()
        reader.SetFileName(stl_path)
        reader.Update()

        # Smooth normals, split at sharp edges
        normals = vtk.vtkPolyDataNormals()
        normals.SetInputConnection(reader.GetOutputPort())
        normals.SetFeatureAngle(30.0)
        normals.SplittingOn()
        normals.ConsistencyOn()
        normals.AutoOrientNormalsOn()
        normals.Update()

        # Camera framing from mesh bounds
        bounds = normals.GetOutput().GetBounds()
        center = [
            (bounds[0] + bounds[1]) / 2,
            (bounds[2] + bounds[3]) / 2,
            (bounds[4] + bounds[5]) / 2,
        ]
        extent = max(
            bounds[1] - bounds[0],
            bounds[3] - bounds[2],
            bounds[5] - bounds[4],
        )

        def _make_actor():
            """Phong-shaded actor from the STL normals pipeline."""
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(normals.GetOutputPort())
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(0.45, 0.68, 0.95)  # light blue
            actor.GetProperty().SetSpecular(0.3)
            actor.GetProperty().SetSpecularPower(20)
            actor.GetProperty().SetAmbient(0.2)
            actor.GetProperty().SetDiffuse(0.8)
            actor.GetProperty().SetInterpolationToPhong()
            return actor

        def _setup_camera(renderer, elev, azim, zoom=0.85):
            """Position camera at given elevation/azimuth angles."""
            distance = extent * 2.5
            elev_rad = np.radians(elev)
            azim_rad = np.radians(azim)
            cam_x = center[0] + distance * np.cos(elev_rad) * np.cos(azim_rad)
            cam_y = center[1] + distance * np.cos(elev_rad) * np.sin(azim_rad)
            cam_z = center[2] + distance * np.sin(elev_rad)
            camera = renderer.GetActiveCamera()
            camera.SetPosition(cam_x, cam_y, cam_z)
            camera.SetFocalPoint(*center)
            camera.SetViewUp(0, 0, 1)
            renderer.ResetCamera()
            camera.Zoom(zoom)

        # View 1 (left): Isometric
        ren1 = vtk.vtkRenderer()
        ren1.AddActor(_make_actor())
        ren1.SetBackground(1.0, 1.0, 1.0)
        ren1.SetViewport(0, 0, 1 / 3, 1.0)
        _setup_camera(ren1, 35, 45)

        # View 2 (center): High-angle rear
        ren2 = vtk.vtkRenderer()
        ren2.AddActor(_make_actor())
        ren2.SetBackground(1.0, 1.0, 1.0)
        ren2.SetViewport(1 / 3, 0, 2 / 3, 1.0)
        _setup_camera(ren2, 65, 220)

        # View 3 (right): Low front profile
        ren3 = vtk.vtkRenderer()
        ren3.AddActor(_make_actor())
        ren3.SetBackground(1.0, 1.0, 1.0)
        ren3.SetViewport(2 / 3, 0, 1.0, 1.0)
        _setup_camera(ren3, 10, 0)

        # Offscreen render window
        render_window = vtk.vtkRenderWindow()
        render_window.SetOffScreenRendering(1)
        render_window.AddRenderer(ren1)
        render_window.AddRenderer(ren2)
        render_window.AddRenderer(ren3)
        render_window.SetSize(size[0], size[1])
        render_window.Render()

        # Write PNG at supersampled resolution
        w2i = vtk.vtkWindowToImageFilter()
        w2i.SetInput(render_window)
        w2i.SetScale(scale)
        w2i.Update()

        writer = vtk.vtkPNGWriter()
        writer.SetFileName(out_png)
        writer.SetInputConnection(w2i.GetOutputPort())
        writer.Write()

        render_window.Finalize()

        return {
            "success": True,
            "png_path": out_png,
            "width": size[0] * scale,
            "height": size[1] * scale,
            "views": ["iso", "high_rear", "front"],
            "renders": {"composite": out_png},
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"VTK render failed: {str(e)}",
            "traceback": traceback.format_exc(),
        }
