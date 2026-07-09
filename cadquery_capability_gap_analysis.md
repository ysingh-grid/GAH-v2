# CadQuery Capability Gap Analysis — GAH-v2

> **Goal:** Identify CadQuery features that are NOT being used, why that matters, and what
> primitives or compile-time helpers we should add to produce richer, smoother, more organic
> models instead of everything looking like stacked blocks.

---

## 1. What We Currently Have

### Primitives in `library.json` (26 total)
| Primitive | CQ Operation | Smooth? |
|---|---|---|
| `box` | `.box()` | ❌ flat |
| `cylinder` | `.cylinder()` | ✓ (circular) |
| `cone` | `Solid.makeCone()` | ✓ (circular) |
| `sphere` | `.sphere()` | ✓ |
| `torus` | `Solid.makeTorus()` | ✓ |
| `wedge` | `.wedge()` | ❌ |
| `pyramid` | `.loft()` (rect→point) | partial |
| `prism` | `.polygon().extrude()` | ❌ flat faces |
| `hexagon_prism` | `.polygon().extrude()` | ❌ |
| `octagonal_prism` | `.polygon().extrude()` | ❌ |
| `hollow_cylinder` | `.circle().circle().extrude()` | ✓ |
| `hollow_box` | `.box().shell()` | ❌ |
| `ellipsoid` | `sphere().transformGeometry()` | ✓ |
| `capsule` | `cylinder + 2×sphere` | ✓ |
| `chamfered_box` | `.box().chamfer()` | ❌ |
| `filleted_box` | `.box().fillet()` | partial |
| `rounded_cylinder` | `.cylinder().fillet()` | partial |
| `ring` | `.circle().circle().extrude()` | ✓ |
| `profile_extrude` | `.polyline/spline().extrude()` | optional smooth |
| `loft` | multi-station loft | ✓ with smooth=True |
| `sweep` | `.sweep()` | ✓ |
| `taper_extrude` | `.polyline().extrude(taper=)` | ❌ no smooth flag |
| `loft_between` | 2-profile loft | ✓ |
| `tube` | double-sweep cut | ✓ |
| `helix_sweep` | `Wire.makeHelix()` | ✓ |
| `revolve` | `.revolve()` | optional smooth |

### FinishOps in schema
`fillet` · `chamfer` · `shell` · `hole` · `cbore` · `csk` · `mirror`

### Patterns
`polar` · `linear`

---

## 2. The Root Problem: Why Models Look Like Blocks

Even though `smooth=True` exists for many primitives, the **planner (LLM) almost never uses it**, because:

1. **The skill guide (`primitive_planning.md`) never mentions `smooth=True`** — the LLM has no guidance to reach for it.
2. **The planner defaults to straight-polygon profiles** because the default for every `smooth` param is `false`.
3. **No arc-aware profile primitive exists** — to make a curved 2D outline you must give the spline control points by hand; there is no `arc_extrude` or `rounded_profile_extrude` that signals "this profile has circular edges".
4. **The `revolve` primitive is underused** — it is the single best tool for organic/turned parts (bottles, vases, knobs, lenses, nozzles) but the planner rarely reaches for it because it is listed last in the library and the playbook only mentions box/cylinder decomposition examples.
5. **`profile_extrude` with `smooth=True` is powerful but the LLM doesn't know what shapes benefit from it** — no examples in skills.

---

## 3. Full CadQuery Capabilities NOT in Our Library/Compiler

### 3.1 Missing Primitives / Templates

| CQ Feature | What It Does | Why We Need It | Priority |
|---|---|---|---|
| `twistExtrude(distance, angle)` | Extrude a 2D profile while rotating it | Twisted columns, auger fins, decorative elements | 🔴 HIGH |
| `Sketch` + `arc()` / `radiusArc()` / `sagittaArc()` / `tangentArcPoint()` | 2D arc segments in profiles | Rounded corners in extruded profiles without point-cloud splines | 🔴 HIGH |
| `Sketch.slot(w, h)` | Stadium-shaped 2D cutout | Mounting slots, track grooves | 🟡 MEDIUM |
| `Sketch.ellipse(a, b)` | Elliptical 2D profile | Elliptic cross-sections, lenses, ergonomic grips | 🟡 MEDIUM |
| `Sketch.bezier(pts, weights)` | Bezier curve profile | True designer curves, organic blobs | 🟡 MEDIUM |
| `parametricCurve(fn, N)` | Curve from math function f(t)→(x,y,z) | NACA airfoils, sine waves, cam profiles | 🟡 MEDIUM |
| `text("str", size, depth)` | Extruded 3D text | Part labels, embossed text, branding | 🟠 LOW-MED |
| `Workplane.cutBlind(depth)` | Blind pocket of specified depth | Blind keyways, pockets, reliefs | 🟡 MEDIUM |
| `Workplane.cutThruAll()` | Through-cut using current face+wire | Simpler than using a huge cut cylinder | 🟠 LOW |
| `Edge.makeSpline(pts, tangents)` | Spline with forced tangents at endpoints | G1-continuous sweep paths | 🟡 MEDIUM |
| `Assembly` + `Location` | Multi-part positioned assemblies | True mechanism assemblies (hinges, linkages) | 🟡 MEDIUM |
| **Face-mounted extrude** | `face.workplane().rect().extrude()` | Boss on an angled or curved face | 🔴 HIGH |
| **Shelled revolve** | `revolve() + shell()` | Hollow vases, cups, bottles with walls | 🔴 HIGH |

### 3.2 FinishOps Missing from Schema

| FinishOp | CQ API | What It Does | Priority |
|---|---|---|---|
| `twistExtrude` as finish | – | N/A (it's a primitive op) | – |
| **`fillet` on `%Circle` edges** | `.edges("%Circle").fillet(r)` | Smooth the top/bottom rims of cylinders | 🔴 HIGH — selector is allowed but planner never uses `%Circle` |
| **`chamfer` on `%Circle` edges** | `.edges("%Circle").chamfer(c)` | Chamfer cylinder rims | 🔴 HIGH |
| **`fillet` on selected face loops** | `.faces(">Z").edges().fillet(r)` | Only fillet the top profile | 🔴 HIGH |
| **`shell` with multiple open faces** | `.faces(">Z or <Z").shell(-t)` | Open both ends (tube from solid) | 🟡 MEDIUM |
| **`rarray` pattern** (rectangular grid) | `.rarray(xs, ys, nx, ny)` | Rectangular bolt patterns, grids | 🟡 MEDIUM |
| **`text` extrude** | `.text(s, size, d)` | Embossed labels | 🟠 LOW |

### 3.3 Selector Gaps — Used Selectors vs All Available

The planner only uses: `|Z`, `>Z`, `<Z`, `>Z[-2]`, `%Circle`

**Unused powerful selectors:**

| Selector | Meaning | Use Case |
|---|---|---|
| `#Z` | Perpendicular to Z (horizontal edges) | Fillet horizontal rims only |
| `>>X` | Farthest in X direction | Fillet/chamfer the leading edge |
| `<X[-2]` | 2nd from most-negative X face | Selecting interior faces |
| `%Line` | All straight edges | Chamfer only straight edges (skip curves) |
| `%Plane` | All planar faces | Shell only flat faces |
| `NearestToPointSelector` | Closest edge/face to a 3D point | Precise local edits |
| `BoxSelector` | Edges inside a 3D bounding box | Region-specific fillets |
| `NOT` / `AND` / `OR` | Logical combination | Complex multi-criteria selection |

### 3.4 Missing Curve/Profile Types for 2D Construction

Our current approach: only `polyline()` or `spline()` through all points.

**What CadQuery also has:**
```python
# Arc from 3 points (start is implicit current position)
wp.threePointArc((5, 3), (10, 0))

# Arc from endpoint + radius (most intuitive)
wp.radiusArc((10, 0), 5)

# Arc from endpoint + sagitta (bulge amount)
wp.sagittaArc((10, 0), 2.0)

# Arc tangent to previous segment
wp.tangentArcPoint((10, 0))

# True Bezier curve
cq.Sketch().bezier([(0,0),(5,10),(10,0)])

# Mathematical curve
wp.parametricCurve(lambda t: (10*cos(t), 10*sin(t), 0), N=50)
```

**None of these are primitives, helpers, or even mentioned in our skills.** The LLM can only generate polylines or pure-splines — no mixed arc-line profiles, no Bezier.

### 3.5 `twistExtrude` — A Completely Missing Primitive

CadQuery has `twistExtrude(distance, angleDegrees)` which extrudes a profile while **rotating it simultaneously**. This produces:
- Twisted columns / pillars
- Auger-style blades
- Helical fin shapes
- Decorative twisted bars

We have `helix_sweep` for coil springs, but no `twist_extrude` primitive that directly maps to this CQ op. Using the `loft` primitive with many stations approximates it but is verbose and less precise.

```python
# What we COULD emit but currently cannot plan:
cq.Workplane("XY").polygon(4, 5).twistExtrude(30, 90)  # 90° twisted square column
```

### 3.6 Face-Relative Workplanes — Not Usable by LLM

Our compiler only supports a fixed global plane (`"XY"` always). CadQuery's power includes:

```python
# Select a face and work relative to it
result.faces(">Y").workplane().rect(5, 5).extrude(2)  # boss on the Y-facing wall

# Work on an angled face
result.faces("<Z[-2]").workplane().circle(3).hole(5)   # hole in slanted face
```

**This is architecturally hard to add** (it requires post-CSG face selection in the plan schema), but it explains why the LLM can't add bosses to side walls without awkward CSG workarounds.

### 3.7 `Assembly` — Completely Absent

The entire `cq.Assembly` system (constraint-based multi-part placement) is unused:

```python
asm = cq.Assembly()
asm.add(bolt, loc=cq.Location((0,0,0)), name="bolt")
asm.add(nut,  loc=cq.Location((0,0,15)), name="nut")
asm.solve()  # constraint solver
```

This is the correct way to produce multi-part models where parts must mate at interfaces. Right now we emit a single `result` compound of unioned bodies — **you can't keep parts separate and positioned correctly** (e.g., lid + box, bolt + nut sitting in a hole).

---

## 4. Why the `smooth=True` Flag is Underused

The `smooth` flag on `profile_extrude`, `revolve`, `loft`, `loft_between`, and `sweep` is perhaps the **single highest-leverage underused feature**. When `smooth=True`, the profile is a Catmull-Rom spline through the control points — a true smooth curve. When `smooth=False` (the default), it's a polyline — flat facets.

**The problem:** Every primitive's default is `smooth=False`, and the planner's skill guides never say:

> "For vases, bottles, organic shapes, lenses, ergonomic grips — set `smooth: true` and place control points to define the desired curvature."

The LLM treats `revolve` like a lathe turning straight segments and never adds the `smooth` flag for curved silhouettes.

---

## 5. The Shelled-Revolve Gap (Hollow Turned Parts)

Hollow turned parts (cups, glasses, vases, bowls, bottles) require:

1. `revolve` with a smooth outer profile
2. `shell` FinishOp to hollow it out

The `shell` FinishOp exists. The `revolve` primitive exists. But:
- The planner's `part_decomposition.md` and `playbook.md` give **zero examples** of `revolve + shell`
- The planner always reaches for `hollow_cylinder` or `hollow_box` instead
- A vase designed as `hollow_cylinder` with flat top is a cylinder, not a vase

---

## 6. The `rarray` Pattern Gap

Our schema has `polar` and `linear` patterns. CadQuery also has:

```python
.rarray(xSpacing, ySpacing, xCount, yCount)  # rectangular grid array
```

Use cases: PCB mounting holes (4-corner), shelf bracket hole grid, bolt pattern grids. We force the LLM to use 4× `linear` pattern or manually positioned holes — clunky.

---

## 7. Summary: Priority Action Table

### 🔴 HIGH PRIORITY — Add These Now

| Gap | Fix | File |
|---|---|---|
| **`smooth` flag never used** | Add 3 examples to `primitive_planning.md` showing `smooth: true` for organic profiles | `skills/primitive_planning.md` |
| **No `revolve + shell` guidance** | Add example to `playbook.md` and `part_decomposition.md` for hollow turned parts | `skills/` |
| **`%Circle` selector never used** | Add to `primitive_planning.md` fillet cheatsheet: "use `%Circle` for all circular edges" | `skills/primitive_planning.md` |
| **No `twist_extrude` primitive** | Add to `library.json`: maps to `cq.Workplane("XY").<profile>.twistExtrude(height, angle)` | `primitives/library.json` |
| **No arc-profile primitive** | Add `arc_extrude` or extend `profile_extrude` with `arc_segments` list param | `primitives/library.json` + `runtime/compile_cadquery.py` |

### 🟡 MEDIUM PRIORITY — Add When Needed

| Gap | Fix | File |
|---|---|---|
| **`rarray` pattern** | Add `PatternType.rarray` to schema + compiler branch | `runtime/schema.py`, `compile_cadquery.py` |
| **`Sketch.slot()` primitive** | Add `slot_extrude` primitive | `primitives/library.json` |
| **`Sketch.ellipse()` primitive** | Add `ellipse_extrude` primitive | `primitives/library.json` |
| **Face-mounted workplane** | Architectural decision needed (post-CSG workplane in schema) | Major change |
| **`Assembly` support** | Architectural decision needed (separate step type) | Major change |

### 🟠 LOW PRIORITY — Future / Nice-to-Have

| Gap | Fix |
|---|---|
| **3D text** | `text_extrude` primitive via `cq.Workplane().text()` |
| **Bezier curve profiles** | Extend `_profile_wp()` helper with `bezier=True` mode |
| **`parametricCurve`** | Add computed-path sweep primitive |
| **Complex selectors** | Add selector examples to skill guides |

---

## 8. The Single Highest-Impact Fix (Do This First)

> **Update `skills/primitive_planning.md` to add a "SMOOTH PROFILES" section** with examples showing:
> 1. Use `smooth: true` on `profile_extrude` / `revolve` for organic, curved shapes
> 2. Use `revolve` + shell FinishOp for hollow turned parts
> 3. Use `%Circle` selector for fillet/chamfer on circular edges

This is a **zero-code change** (edit one Markdown file) and immediately makes every planner run smarter. The compute infrastructure is already there — it just needs the guidance signal.

The second-highest fix:

> **Add a `twist_extrude` primitive** to `library.json` + a compile helper, enabling twisted columns, fins, and decorative shapes that are currently impossible.

---

## 9. Audit of Past Generated Models

Based on the artifact structure (only 1 run in `artifacts/forgecad/`), recent planner output has been either:
- Pure box stacks (mechanical brackets, mounting plates)
- Cylinder stacks (flanges, shafts)
- No observed use of: `loft`, `sweep`, `tube`, `helix_sweep`, `revolve`, `loft_between`, `profile_extrude` with `smooth=True`

This confirms the hypothesis: **the planner defaults to the simplest primitives regardless of whether the shape warrants organic geometry**, because the skill guidance doesn't push it toward smoothness.

---

## References

- CadQuery Docs: https://cadquery.readthedocs.io/en/latest/
- CQ Workplane API: https://cadquery.readthedocs.io/en/latest/apireference.html
- CQ Sketch API: https://cadquery.readthedocs.io/en/latest/sketch.html
- GAH-v2 primitives: `primitives/library.json`
- GAH-v2 compiler: `runtime/compile_cadquery.py`
- GAH-v2 schema: `runtime/schema.py`
- GAH-v2 skill guides: `skills/`
