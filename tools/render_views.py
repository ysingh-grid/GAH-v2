def render_views(stl_path: str, run_id: str, section: dict | None = None) -> dict:
    """
    Render a single composite PNG with FIVE side-by-side views of an STL,
    using VTK with Phong shading + bold black edge/silhouette overlays
    (server-side, offscreen, no GUI).

    Views (left -> right):
      - front    (true orthographic, look +Y)  — XZ face, heights/widths
      - side     (true orthographic, look -X)  — YZ face, depth profile
      - top      (true orthographic, look -Z)  — XY face, hole/slot layout
      - iso      (perspective, elev35/azim45)  — overall 3D shape
      - section  (cutaway half-solid)          — interior walls/cavities

    Section plane:
      Plan-driven when `section` is provided as {"normal": [x,y,z],
      "point": [x,y,z]}; otherwise auto — through the center of mass with the
      normal along the SHORTEST bounding-box axis (plane spans the two longest
      dims = maximum cross-section revealed).

    Args:
        stl_path: Absolute (or repo-relative) path to the STL file.
        run_id: Unique identifier for the run; names the output PNG.
        section: Optional {"normal":[x,y,z], "point":[x,y,z]} cut plane.

    Returns:
        On success:
          {"success": True, "png_path": str, "width": int, "height": int,
           "views": ["front","side","top","iso","section"],
           "renders": {"composite": png_path}}
        On failure:
          {"success": False, "error": str}

    Implementation note:
        VTK's offscreen renderer makes Cocoa/OpenGL calls that must run on the
        OS main thread. When invoked from a uvicorn thread-pool worker (a
        background thread), this causes a silent segfault that kills the whole
        server process. To avoid this, the actual VTK work is performed inside
        a fresh subprocess — which always starts with its own main thread —
        and the result is returned as JSON. Same pattern as execute_cadquery.py.
    """
    import json
    import os
    import shutil
    import subprocess
    import sys
    import tempfile

    if not os.path.exists(stl_path):
        return {"success": False, "error": f"STL file not found at {stl_path}"}

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    wrapper = f"""
import sys, json, os
sys.path.insert(0, {repr(repo_root)})
from tools.render_views import _do_render
result = _do_render({repr(stl_path)}, {repr(run_id)}, section={repr(section)})
print(json.dumps(result))
"""

    try:
        with tempfile.NamedTemporaryFile(
            suffix=".py", delete=False, mode="w", encoding="utf-8"
        ) as tmp:
            tmp.write(wrapper)
            tmp_path = tmp.name

        env = os.environ.copy()
        env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")

        # The pip VTK wheel uses a GLX/X OpenGL backend that needs a live X
        # display even with SetOffScreenRendering(1). In a headless container
        # there is none, so wrap the render in a throwaway virtual framebuffer
        # via xvfb-run (-a picks a free display number). On macOS dev there is
        # no xvfb-run and VTK renders offscreen via Cocoa, so fall back to plain.
        cmd = [sys.executable, tmp_path]
        if shutil.which("xvfb-run"):
            cmd = ["xvfb-run", "-a", *cmd]

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,  # generous: VTK startup can be slow on first call
            env=env,
        )

        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        if proc.returncode != 0:
            return {
                "success": False,
                "error": (
                    f"render subprocess exited with code {proc.returncode}. "
                    f"stderr: {proc.stderr[:2000]}"
                ),
            }

        output = proc.stdout.strip()
        if not output:
            return {
                "success": False,
                "error": f"render subprocess produced no output. stderr: {proc.stderr[:2000]}",
            }

        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {
                "success": False,
                "error": f"render subprocess output is not valid JSON: {output[:500]}",
            }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "render subprocess timed out after 120 s"}
    except Exception as exc:
        return {"success": False, "error": f"render subprocess launch failed: {exc}"}


def _do_render(stl_path: str, run_id: str, section: dict | None = None) -> dict:
    """
    Execute the VTK five-view render in the *current* process.

    This must only be called from a process whose main thread is available for
    Cocoa/OpenGL (i.e. NOT from a uvicorn thread-pool worker). Call render_views()
    instead — it guarantees isolation via a subprocess.
    """
    import math
    import os
    import traceback

    from tools.artifacts import run_dir

    outputs_dir = str(run_dir(run_id))
    out_png = os.path.join(outputs_dir, "threeview.png")  # name kept for path-compat

    try:
        import numpy as np
        import vtk

        size = (4000, 800)  # five 800-wide panels in a row
        scale = 2

        # Read STL
        reader = vtk.vtkSTLReader()
        reader.SetFileName(stl_path)
        reader.Update()

        # Smooth normals, split at sharp edges (feeds both shading and edges).
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
        dims = [bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4]]
        extent = max(dims) or 1.0

        # ── reusable actor builders (parameterized by producer port) ──────────
        def _solid_actor(port):
            """Matte-shaded actor — flat even shading reads better than glossy."""
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(port)
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            p = actor.GetProperty()
            p.SetColor(0.80, 0.80, 0.82)  # light neutral gray
            p.SetSpecular(0.0)            # kill glare that washes out features
            p.SetAmbient(0.35)
            p.SetDiffuse(0.65)
            p.SetInterpolationToPhong()
            return actor

        def _edges_actor(port):
            """Bold black feature + boundary edges (view-independent hard edges).

            vtkFeatureEdges pulls the model's sharp creases (dihedral > angle)
            and open boundaries; tubing them makes thick crisp outlines instead
            of 1px hairlines a flat shaded solid hides.
            """
            fe = vtk.vtkFeatureEdges()
            fe.SetInputConnection(port)
            fe.BoundaryEdgesOn()
            fe.FeatureEdgesOn()
            fe.SetFeatureAngle(20.0)
            fe.ManifoldEdgesOff()
            fe.NonManifoldEdgesOff()
            fe.ColoringOff()
            tube = vtk.vtkTubeFilter()
            tube.SetInputConnection(fe.GetOutputPort())
            tube.SetRadius(extent * 0.003)
            tube.SetNumberOfSides(6)
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(tube.GetOutputPort())
            mapper.ScalarVisibilityOff()
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(0, 0, 0)
            actor.GetProperty().SetLighting(False)
            return actor

        def _silhouette_actor(port, renderer):
            """View-dependent outer contour — catches CURVED silhouettes (helmet,
            sphere, cylinder) that vtkFeatureEdges misses (no sharp crease).
            Bound to this renderer's camera; updates on Render()."""
            sil = vtk.vtkPolyDataSilhouette()
            sil.SetInputConnection(port)
            sil.SetCamera(renderer.GetActiveCamera())
            sil.SetEnableFeatureAngle(0)  # silhouette only; feature edges handled above
            tube = vtk.vtkTubeFilter()
            tube.SetInputConnection(sil.GetOutputPort())
            tube.SetRadius(extent * 0.003)
            tube.SetNumberOfSides(6)
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(tube.GetOutputPort())
            mapper.ScalarVisibilityOff()
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(0, 0, 0)
            actor.GetProperty().SetLighting(False)
            return actor

        def _add_label(renderer, text):
            """Bold black caption centered at the bottom of one panel's viewport."""
            actor = vtk.vtkTextActor()
            actor.SetInput(text.upper())
            actor.GetTextProperty().SetColor(0, 0, 0)
            actor.GetTextProperty().SetFontSize(28)
            actor.GetTextProperty().BoldOn()
            actor.GetTextProperty().SetJustificationToCentered()
            actor.GetTextProperty().SetVerticalJustificationToBottom()
            coord = actor.GetPositionCoordinate()
            coord.SetCoordinateSystemToNormalizedViewport()
            coord.SetValue(0.5, 0.03)
            renderer.AddActor2D(actor)

        def _frame_ortho(renderer, view_dir, view_up):
            """True orthographic framing: parallel projection along view_dir."""
            cam = renderer.GetActiveCamera()
            cam.ParallelProjectionOn()
            dx, dy, dz = view_dir
            cam.SetFocalPoint(*center)
            cam.SetPosition(
                center[0] - dx * extent * 3,
                center[1] - dy * extent * 3,
                center[2] - dz * extent * 3,
            )
            cam.SetViewUp(*view_up)
            renderer.ResetCamera()
            cam.Zoom(0.9)

        def _frame_iso(renderer, elev, azim):
            distance = extent * 2.5
            er, ar = np.radians(elev), np.radians(azim)
            cam = renderer.GetActiveCamera()
            cam.SetPosition(
                center[0] + distance * np.cos(er) * np.cos(ar),
                center[1] + distance * np.cos(er) * np.sin(ar),
                center[2] + distance * np.sin(er),
            )
            cam.SetFocalPoint(*center)
            cam.SetViewUp(0, 0, 1)
            renderer.ResetCamera()
            cam.Zoom(0.85)

        render_window = vtk.vtkRenderWindow()
        render_window.SetOffScreenRendering(1)
        render_window.SetSize(size[0], size[1])

        n = 5  # front, side, top, iso, section

        # ── ortho + iso panels (share the full-solid pipeline) ────────────────
        panels = [
            ("front", lambda r: _frame_ortho(r, (0, 1, 0), (0, 0, 1))),
            ("side",  lambda r: _frame_ortho(r, (-1, 0, 0), (0, 0, 1))),
            ("top",   lambda r: _frame_ortho(r, (0, 0, -1), (0, 1, 0))),
            ("iso",   lambda r: _frame_iso(r, 35, 45)),
        ]
        for i, (name, setup) in enumerate(panels):
            ren = vtk.vtkRenderer()
            ren.SetViewport(i / n, 0, (i + 1) / n, 1.0)
            ren.SetBackground(1.0, 1.0, 1.0)
            ren.AddActor(_solid_actor(normals.GetOutputPort()))
            ren.AddActor(_edges_actor(normals.GetOutputPort()))
            setup(ren)  # position camera (needs actors first for ResetCamera)
            ren.AddActor(_silhouette_actor(normals.GetOutputPort(), ren))
            _add_label(ren, name)
            render_window.AddRenderer(ren)

        # ── section panel: cutaway half-solid ─────────────────────────────────
        # Plan-driven plane if provided, else auto: center of mass + shortest-axis
        # normal (plane spans the two longest dims = maximum cross-section).
        if section and section.get("normal") and section.get("point"):
            s_normal = [float(c) for c in section["normal"]]
            s_point = [float(c) for c in section["point"]]
        else:
            com = vtk.vtkCenterOfMass()
            com.SetInputData(normals.GetOutput())
            com.SetUseScalarsAsWeights(False)
            com.Update()
            s_point = list(com.GetCenter())
            axis = dims.index(min(dims))  # shortest extent → span the two longest
            s_normal = [0.0, 0.0, 0.0]
            s_normal[axis] = 1.0

        plane = vtk.vtkPlane()
        plane.SetOrigin(*s_point)
        plane.SetNormal(*s_normal)
        plane_collection = vtk.vtkPlaneCollection()
        plane_collection.AddItem(plane)
        # vtkClipPolyData does NOT cap the cut — it just deletes triangles beyond
        # the plane, leaving an OPEN boundary. Viewed face-on down the cut normal
        # that reads as "just the exterior again" (MEASURED: a fully-solid part
        # rendered near-identical to the front view — no visual signal the
        # interior was solid, not hollow, letting a false pass through). Use
        # vtkClipClosedSurface instead: it auto-caps the cut with a real face, so
        # a solid part shows a FILLED cap (no ring/void) and a hollow part shows
        # the true wall cross-section — the whole point of a section view.
        clip = vtk.vtkClipClosedSurface()
        clip.SetClippingPlanes(plane_collection)
        clip.SetInputConnection(normals.GetOutputPort())
        clip.SetGenerateFaces(1)
        clip.SetScalarModeToColors()
        clip.SetBaseColor(0.80, 0.80, 0.82)   # passthrough body — matches _solid_actor's matte gray
        clip.SetClipColor(0.90, 0.35, 0.15)   # cap face — distinct warm color, the cut itself
        clip.Update()

        def _section_solid_actor(port):
            """Like _solid_actor, but scalar-colored so the cap face's distinct
            color (set above) actually renders instead of being flattened to one
            uniform actor color."""
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(port)
            mapper.ScalarVisibilityOn()
            mapper.SetScalarModeToUseCellData()
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            p = actor.GetProperty()
            p.SetSpecular(0.0)
            p.SetAmbient(0.35)
            p.SetDiffuse(0.65)
            p.SetInterpolationToPhong()
            return actor

        sec = vtk.vtkRenderer()
        sec.SetViewport(4 / n, 0, 1.0, 1.0)
        sec.SetBackground(1.0, 1.0, 1.0)
        sec.AddActor(_section_solid_actor(clip.GetOutputPort()))
        sec.AddActor(_edges_actor(clip.GetOutputPort()))
        nlen = math.sqrt(sum(c * c for c in s_normal)) or 1.0
        un = [c / nlen for c in s_normal]
        cam = sec.GetActiveCamera()
        cam.ParallelProjectionOn()
        cam.SetFocalPoint(*center)
        cam.SetPosition(  # -normal side, looking into the open cut face
            center[0] - un[0] * extent * 3,
            center[1] - un[1] * extent * 3,
            center[2] - un[2] * extent * 3,
        )
        cam.SetViewUp(*((0, 0, 1) if abs(un[2]) < 0.9 else (0, 1, 0)))
        sec.ResetCamera()
        cam.Zoom(0.9)
        _add_label(sec, "section")
        render_window.AddRenderer(sec)

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
            "views": ["front", "side", "top", "iso", "section"],
            "renders": {"composite": out_png},
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"VTK render failed: {str(e)}",
            "traceback": traceback.format_exc(),
        }
