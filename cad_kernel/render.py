"""
render.py — headless, GPU-free render of a CadQuery solid to a PNG.

Uses matplotlib (CPU only) so it runs on any machine / CI with no display or
OpenGL. Tessellates the solid and draws shaded triangles from several viewpoints.
Rendering happens AFTER verification — the picture is a convenience, never the
evidence.
"""

import matplotlib
matplotlib.use("Agg")  # headless backend
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np


def _tessellate(solid, tol=0.2):
    # Accept a Workplane (possibly many bodies) or a single Solid; merge all bodies.
    objs = solid.vals() if hasattr(solid, "vals") else [solid]
    allV = []
    allF = []
    offset = 0
    for o in objs:
        shape = o.val() if hasattr(o, "val") else o
        try:
            verts, tris = shape.tessellate(tol)
        except Exception:
            continue
        allV.extend([[v.x, v.y, v.z] for v in verts])
        allF.extend([[a + offset, b + offset, c + offset] for (a, b, c) in tris])
        offset += len(verts)
    V = np.array(allV, dtype=float)
    F = np.array(allF, dtype=int)
    return V, F


def render_solid(solid, out_path: str, views=((30, -60), (30, 30), (90, -90)), tol=0.2):
    """Render `solid` to `out_path` (PNG) from a few angles. Returns out_path."""
    V, F = _tessellate(solid, tol)
    tris = V[F]  # (n,3,3)

    # shading: lambert against a fixed light, so it reads as 3D
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.divide(n, ln, out=np.zeros_like(n), where=ln != 0)
    light = np.array([0.3, 0.3, 1.0]); light = light / np.linalg.norm(light)
    shade = 0.35 + 0.65 * np.clip(n @ light, 0, 1)

    fig = plt.figure(figsize=(4 * len(views), 4))
    ctr = V.mean(axis=0)
    span = float((V.max(axis=0) - V.min(axis=0)).max()) or 1.0
    for i, (elev, azim) in enumerate(views, 1):
        ax = fig.add_subplot(1, len(views), i, projection="3d")
        colors = np.column_stack([0.30 * shade, 0.55 * shade, 0.85 * shade,
                                  np.ones_like(shade)])
        pc = Poly3DCollection(tris, facecolors=colors, edgecolors=(0, 0, 0, 0.08),
                              linewidths=0.2)
        ax.add_collection3d(pc)
        for axis, c in zip("xyz", ctr):
            getattr(ax, f"set_{axis}lim")(c - span / 2, c + span / 2)
        ax.set_box_aspect((1, 1, 1))
        ax.view_init(elev=elev, azim=azim)
        ax.set_axis_off()
        ax.set_title(f"view {i}", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return out_path
