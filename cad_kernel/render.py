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


def render_solid(solid, out_path: str,
                 views=(("front", 0, -90), ("side", 0, 0), ("top", 90, -90), ("iso", 30, -60)),
                 tol=0.2):
    """Render `solid` to `out_path` (PNG). Returns out_path.

    B3 orientation cues: named views (front/side/top + iso) and a labeled X/Y/Z axis triad in
    every panel, so a (blind) agent and the vision critic can reason about ORIENTATION ("the part
    facing -Y", "the slab on +Z") instead of guessing. `views` items may be (name, elev, azim) or
    the legacy (elev, azim). Determinism note: this only improves the picture the perceptual loop
    sees — it does not, by itself, make orientation correct."""
    V, F = _tessellate(solid, tol)
    tris = V[F]  # (n,3,3)

    # shading: lambert against a fixed light, so it reads as 3D
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.divide(n, ln, out=np.zeros_like(n), where=ln != 0)
    light = np.array([0.3, 0.3, 1.0]); light = light / np.linalg.norm(light)
    shade = 0.35 + 0.65 * np.clip(n @ light, 0, 1)

    # normalize views to (name, elev, azim)
    norm_views = []
    for idx, v in enumerate(views, 1):
        if len(v) == 3:
            norm_views.append((str(v[0]), float(v[1]), float(v[2])))
        else:
            norm_views.append((f"view {idx}", float(v[0]), float(v[1])))

    fig = plt.figure(figsize=(4 * len(norm_views), 4))
    ctr = V.mean(axis=0)
    span = float((V.max(axis=0) - V.min(axis=0)).max()) or 1.0
    tri_len = 0.28 * span
    origin = V.min(axis=0) - 0.08 * span  # anchor the triad just off the model's min corner
    triad = [((1, 0, 0), "X", "#d62728"), ((0, 1, 0), "Y", "#2ca02c"), ((0, 0, 1), "Z", "#1f77b4")]

    for i, (name, elev, azim) in enumerate(norm_views, 1):
        ax = fig.add_subplot(1, len(norm_views), i, projection="3d")
        colors = np.column_stack([0.30 * shade, 0.55 * shade, 0.85 * shade,
                                  np.ones_like(shade)])
        pc = Poly3DCollection(tris, facecolors=colors, edgecolors=(0, 0, 0, 0.08),
                              linewidths=0.2)
        ax.add_collection3d(pc)
        # labeled X/Y/Z axis triad (orientation reference)
        for (dx, dy, dz), lbl, col in triad:
            ax.quiver(origin[0], origin[1], origin[2],
                      dx * tri_len, dy * tri_len, dz * tri_len,
                      color=col, linewidth=1.4, arrow_length_ratio=0.18)
            ax.text(origin[0] + dx * tri_len * 1.15,
                    origin[1] + dy * tri_len * 1.15,
                    origin[2] + dz * tri_len * 1.15,
                    lbl, color=col, fontsize=8, fontweight="bold")
        for axis, c in zip("xyz", ctr):
            getattr(ax, f"set_{axis}lim")(c - span / 2, c + span / 2)
        ax.set_box_aspect((1, 1, 1))
        ax.view_init(elev=elev, azim=azim)
        ax.set_axis_off()
        ax.set_title(name, fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return out_path
