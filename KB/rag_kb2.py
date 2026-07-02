"""KB2: Error-Solution Pattern Database for CadQuery/OCCT errors.

Simple keyword-matching retrieval — no embeddings needed.
Each pattern has trigger keywords matched against the error traceback,
plus a structured fix description injected into the Error Refiner prompt.

Sources:
  - CadQuery GitHub issues (referenced by number)
  - Text-to-CadQuery paper (arXiv:2505.06507) Appendix A.4
  - Empirical testing during AutoFab development
  - CadQuery documentation (cadquery.readthedocs.io)
"""

from dataclasses import dataclass


@dataclass
class ErrorPattern:
    """A known error pattern with its fix."""
    id: str
    name: str
    trigger_keywords: list[str]       # ALL must appear in traceback (AND)
    trigger_any: list[str] = None     # ANY may appear in traceback (OR) — optional extra filter
    root_cause: str = ""
    fix_description: str = ""
    code_before: str = ""             # Example bad code (optional)
    code_after: str = ""              # Example fixed code (optional)
    priority: int = 0                 # Higher = matched first on ties


# ---------------------------------------------------------------------------
# Error pattern database
# ---------------------------------------------------------------------------

PATTERNS: list[ErrorPattern] = [

    # === FILLET / CHAMFER ERRORS ===

    ErrorPattern(
        id="fillet_too_large",
        name="Fillet radius too large",
        trigger_keywords=["StdFail_NotDone"],
        trigger_any=["fillet", "Fillet"],
        root_cause=(
            "The fillet radius exceeds half the length of the shortest adjacent edge. "
            "OCCT cannot construct the fillet geometry."
        ),
        fix_description=(
            "1. Reduce the fillet radius. It must be LESS than half the shortest edge adjacent to the filleted edge.\n"
            "2. If unsure of safe radius, use a conservative value (e.g., 1mm) or compute it: "
            "min_edge_len = min(e.Length() for e in result.edges().vals()); safe_radius = min_edge_len * 0.4\n"
            "3. Alternative: wrap fillet in try/except and fall back to a smaller radius or skip fillet entirely.\n"
            "4. Consider applying fillet BEFORE boolean operations (cut/union), not after."
        ),
        code_before='result = base.edges("|Z").fillet(5)  # 5mm may be too large',
        code_after=(
            'fillet_radius = 2  # Use conservative radius < half shortest edge\n'
            'try:\n'
            '    result = base.edges("|Z").fillet(fillet_radius)\n'
            'except:\n'
            '    result = base  # Skip fillet if it fails'
        ),
        priority=10,
    ),

    ErrorPattern(
        id="chamfer_too_large",
        name="Chamfer size too large",
        trigger_keywords=["StdFail_NotDone"],
        trigger_any=["chamfer", "Chamfer"],
        root_cause=(
            "The chamfer distance exceeds the shortest adjacent edge length. "
            "Similar to fillet failures but for chamfer operations."
        ),
        fix_description=(
            "1. Reduce chamfer distance to less than the shortest adjacent edge.\n"
            "2. If chamfering after a fillet, make chamfer distance slightly smaller than fillet radius.\n"
            "3. Wrap in try/except with fallback to smaller chamfer or skip."
        ),
        priority=9,
    ),

    ErrorPattern(
        id="fillet_after_clean",
        name="Fillet fails after boolean with clean=True",
        trigger_keywords=["StdFail_NotDone", "fillet"],
        root_cause=(
            "The .clean() operation (called automatically by boolean operations like .cut() and .union()) "
            "merges coplanar faces and collinear edges via ShapeUpgrade_UnifySameDomain. "
            "This destroys the edge references that .fillet() needs."
        ),
        fix_description=(
            "1. Apply .fillet() BEFORE boolean operations, not after.\n"
            "2. Or pass clean=False to the boolean: .cut(tool, clean=False) or .union(other, clean=False)\n"
            "3. Or use the 2D Sketch API: .sketch().fillet() on sketch vertices before extrude."
        ),
        priority=8,
    ),

    # === BOOLEAN OPERATION ERRORS ===

    ErrorPattern(
        id="boolean_construction_error",
        name="Boolean operation construction error",
        trigger_keywords=["Standard_ConstructionError"],
        trigger_any=["cut", "union", "intersect", "fuse", "common"],
        root_cause=(
            "The boolean operation (cut/union/intersect) failed due to near-coincident surfaces, "
            "numerical precision issues, or incompatible geometry."
        ),
        fix_description=(
            "1. Pass clean=False to the boolean operation: .cut(tool, clean=False)\n"
            "2. Try fuzzy boolean mode with a tolerance: .cut(tool, tol=1e-3)\n"
            "3. Ensure shapes actually overlap for cut/intersect operations — check positioning.\n"
            "4. Avoid building shapes on separate Workplanes then combining; use a single workplane chain."
        ),
        priority=7,
    ),

    ErrorPattern(
        id="boolean_zero_norm",
        name="Boolean gp_Dir zero norm error",
        trigger_keywords=["Standard_ConstructionError", "gp_Dir", "zero norm"],
        root_cause=(
            "A boolean operation produced a degenerate direction vector (zero length). "
            "Usually caused by near-coincident or tangent surfaces at the boolean boundary."
        ),
        fix_description=(
            "1. Offset one shape slightly (0.001mm) so surfaces aren't exactly coincident.\n"
            "2. Pass clean=False: .cut(tool, clean=False)\n"
            "3. Use fuzzy boolean: .cut(tool, tol=1e-3)"
        ),
        priority=8,
    ),

    ErrorPattern(
        id="revolve_360_boolean",
        name="360-degree revolve boolean failure",
        trigger_keywords=["StdFail_NotDone"],
        trigger_any=["revolve", "Revolution"],
        root_cause=(
            "OCCT has known issues with boolean operations on 360-degree revolved solids. "
            "The seam edge of a full revolution creates numerical problems."
        ),
        fix_description=(
            "1. Revolve to 359.9 degrees instead of 360.\n"
            "2. Pass clean=False to subsequent boolean operations.\n"
            "3. Alternative: create two 180-degree halves and union them."
        ),
        priority=6,
    ),

    # === WIRE / SKETCH CLOSURE ERRORS ===

    ErrorPattern(
        id="no_pending_wires",
        name="No pending wires present",
        trigger_keywords=["No pending wires"],
        root_cause=(
            "Called .extrude(), .revolve(), or .loft() but no wires are registered as pending. "
            "This happens when you select existing geometry via .faces()/.wires()/.edges() — "
            "these selections do NOT auto-register as pending wires. Only sketch operations "
            "like .rect(), .circle(), .polygon() auto-register."
        ),
        fix_description=(
            "1. Add .wires().toPending() before .extrude():\n"
            "   result.faces('>Z').wires().toPending().workplane().extrude(depth)\n"
            "2. Or redraw the shape on the selected face:\n"
            "   result.faces('>Z').workplane().rect(w, h).extrude(depth)\n"
            "3. Make sure .close() is called before .extrude() when drawing with .lineTo()/.line()."
        ),
        code_before='result = base.faces(">Z").extrude(10)  # No pending wires!',
        code_after='result = base.faces(">Z").workplane().rect(20, 20).extrude(10)',
        priority=10,
    ),

    ErrorPattern(
        id="wire_not_closed",
        name="Wire not closed before extrude",
        trigger_keywords=["outer wire is not closed"],
        root_cause=(
            "The sketch path was not closed before calling .extrude() or .revolve(). "
            "A wire must form a closed loop to define a face that can be extruded."
        ),
        fix_description=(
            "1. Add .close() before .extrude():\n"
            "   .lineTo(x, y).lineTo(x2, y2).close().extrude(depth)\n"
            "2. Verify the last point connects back to the first point of the sketch.\n"
            "3. If using .spline(), ensure it returns to the start point or call .close() after."
        ),
        priority=10,
    ),

    # === ARC CONSTRUCTION ERRORS ===

    ErrorPattern(
        id="arc_collinear",
        name="threePointArc with collinear points",
        trigger_keywords=["GC_MakeArcOfCircle"],
        root_cause=(
            "threePointArc() was called with three nearly collinear points. The OCCT kernel "
            "cannot compute an arc through collinear points (it would be a line, not an arc). "
            "This is the most common runtime error in LLM-generated CadQuery code "
            "(documented in Text-to-CadQuery paper)."
        ),
        fix_description=(
            "1. Use .radiusArc(endpoint, radius) instead of .threePointArc() — it's more robust.\n"
            "2. If you must use threePointArc, ensure the midpoint is offset from the chord line "
            "by at least 1e-4 times the chord length.\n"
            "3. For simple curves, consider .sagittaArc(endpoint, sagitta) which is also more robust.\n"
            "4. Alternative: use .spline() with control points for complex curves."
        ),
        code_before='.threePointArc((5, 1), (10, 0))  # Nearly collinear!',
        code_after='.radiusArc((10, 0), 8)  # Specify radius directly',
        priority=10,
    ),

    ErrorPattern(
        id="radius_arc_too_small",
        name="radiusArc radius too small to reach endpoint",
        trigger_keywords=["radius", "arc"],
        trigger_any=["Standard_Failure", "GC_MakeArcOfCircle", "Geom_UndefinedValue"],
        root_cause=(
            "The radius provided to radiusArc() is smaller than half the distance "
            "to the endpoint. The arc cannot physically reach the endpoint with that radius."
        ),
        fix_description=(
            "1. Increase the radius. Minimum radius = half the chord length between current point and endpoint.\n"
            "2. Calculate: import math; chord = math.dist(current_pt, end_pt); min_radius = chord / 2\n"
            "3. Use a radius at least 10% larger than the minimum for numerical safety."
        ),
        priority=5,
    ),

    # === EXTRUSION ERRORS ===

    ErrorPattern(
        id="extrude_both_crash",
        name="Extrude with both=True crashes",
        trigger_keywords=["extrude"],
        trigger_any=["Segmentation fault", "SIGSEGV", "both"],
        root_cause=(
            "The both=True parameter for .extrude() has a known bug in some CadQuery/OCCT versions "
            "that can cause a segfault."
        ),
        fix_description=(
            "1. Avoid both=True. Instead, extrude in each direction separately and union:\n"
            "   top = base.extrude(depth)\n"
            "   bottom = base.extrude(-depth)\n"
            "   result = top.union(bottom)\n"
            "2. Or use .extrude(depth) and translate the result to center it."
        ),
        priority=6,
    ),

    # === LOFT ERRORS ===

    ErrorPattern(
        id="loft_inconsistent_profiles",
        name="Loft profiles are inconsistent",
        trigger_keywords=["profiles are inconsistent"],
        root_cause=(
            "The cross-section profiles for .loft() have different numbers of edges, "
            "different winding directions, or incompatible topology."
        ),
        fix_description=(
            "1. Ensure all loft sections have the same number of edges and consistent winding direction.\n"
            "2. Use the same shape type for all sections (e.g., all circles or all rectangles).\n"
            "3. If lofting between different shapes, try adding intermediate sections to smooth the transition.\n"
            "4. Check that all sections are closed wires."
        ),
        priority=7,
    ),

    ErrorPattern(
        id="loft_single_wire",
        name="Loft with only one wire",
        trigger_keywords=["More than one wire is required"],
        root_cause=(
            "loft() requires at least two cross-section wires but only one was provided."
        ),
        fix_description=(
            "1. Ensure you have at least two workplanes with shapes drawn on them before calling .loft().\n"
            "2. Call .toPending() on each wire if selecting from existing geometry.\n"
            "3. Typical pattern:\n"
            "   result = (cq.Workplane('XY')\n"
            "     .rect(10, 10)          # First section\n"
            "     .workplane(offset=20)  # Move up\n"
            "     .circle(5)             # Second section\n"
            "     .loft())               # Loft between them"
        ),
        priority=7,
    ),

    # === SHELL ERRORS ===

    ErrorPattern(
        id="shell_too_thin",
        name="Shell thickness too small",
        trigger_keywords=["StdFail_NotDone"],
        trigger_any=["shell", "Shell"],
        root_cause=(
            "The shell thickness is too small relative to the geometry. "
            "OCCT's internal tolerance is ~0.0001, so very thin shells fail silently."
        ),
        fix_description=(
            "1. Increase shell thickness to at least 0.1% of the smallest geometry dimension.\n"
            "2. Simplify the geometry before shelling — fewer faces = fewer failure points.\n"
            "3. Shell before applying fillets/chamfers, not after."
        ),
        priority=5,
    ),

    # === SELECTOR ERRORS ===

    ErrorPattern(
        id="selector_empty",
        name="Selector returned no results",
        trigger_keywords=["IndexError"],
        trigger_any=["faces", "edges", "vertices", "wires", "val()"],
        root_cause=(
            "A CadQuery selector (e.g., .faces('>Z'), .edges('|X')) returned an empty result set, "
            "then a downstream operation like .val() or .fillet() crashed on the empty selection."
        ),
        fix_description=(
            "1. Verify the selector string is correct:\n"
            "   >Z = most positive Z face, <Z = most negative Z face\n"
            "   |Z = faces parallel to Z axis (vertical faces), #Z = edges perpendicular to Z\n"
            "   >X = rightmost face, <X = leftmost face\n"
            "2. Non-linear edges (arcs, splines) are NOT returned by directional selectors. "
            "Use %Circle or %Line type selectors for curved edges.\n"
            "3. After boolean operations with clean=True, edge/face indices may have changed. "
            "Use directional selectors instead of index-based selection."
        ),
        priority=8,
    ),

    # === IMPORT / ENVIRONMENT ERRORS ===

    ErrorPattern(
        id="import_ocp_vscode",
        name="Attempted to import ocp_vscode",
        trigger_keywords=["ocp_vscode"],
        root_cause="The code tried to import ocp_vscode for visualization, which is not available in the sandbox.",
        fix_description=(
            "1. Remove ALL lines containing ocp_vscode, show(), show_object(), or save_screenshot().\n"
            "2. Remove any visualization imports: from ocp_vscode import show\n"
            "3. The AutoFab executor handles export — do NOT call cq.exporters.export() either."
        ),
        priority=10,
    ),

    ErrorPattern(
        id="import_not_available",
        name="Unavailable import",
        trigger_keywords=["ModuleNotFoundError"],
        root_cause="The code tried to import a module not available in the sandbox.",
        fix_description=(
            "1. Only these imports are available: cadquery (as cq), math, numpy.\n"
            "2. Remove any imports of: ocp_vscode, matplotlib, PIL, scipy, trimesh, etc.\n"
            "3. Do NOT import cq_warehouse, cq_gears, or other CadQuery plugins."
        ),
        priority=10,
    ),

    ErrorPattern(
        id="exporters_call",
        name="Direct call to cq.exporters",
        trigger_keywords=["exporters"],
        trigger_any=["export", "Export"],
        root_cause="The code called cq.exporters.export() directly. The AutoFab executor handles file export.",
        fix_description=(
            "1. Remove ALL lines calling cq.exporters.export().\n"
            "2. Just assign the final shape to `result` — the executor handles STEP/STL export.\n"
            "3. Do not write files or save anything — the sandbox handles all I/O."
        ),
        priority=9,
    ),

    # === GENERAL OCCT ERRORS ===

    ErrorPattern(
        id="stdfail_generic",
        name="Generic StdFail_NotDone (unknown cause)",
        trigger_keywords=["StdFail_NotDone"],
        root_cause=(
            "The OCCT kernel reported a generic failure. OCCT does not provide detailed diagnostics "
            "for this error class (confirmed in CadQuery issue #876). The most common causes are:\n"
            "- Fillet/chamfer radius too large\n"
            "- Boolean operation on incompatible geometry\n"
            "- Shell operation on complex geometry\n"
            "- Offset operation failure"
        ),
        fix_description=(
            "1. If the error is near a .fillet() or .chamfer() call: reduce the radius.\n"
            "2. If the error is near a .cut()/.union(): try clean=False or tol=1e-3.\n"
            "3. If the error is near a .shell(): increase thickness or simplify geometry.\n"
            "4. General strategy: simplify the geometry step by step. Comment out operations "
            "from the bottom up until the error disappears, then fix the failing operation.\n"
            "5. Wrap risky operations (fillet, shell, complex booleans) in try/except."
        ),
        priority=1,  # Low priority — matches last as fallback
    ),

    ErrorPattern(
        id="syntax_error",
        name="Python syntax error",
        trigger_keywords=["SyntaxError"],
        root_cause="The generated code has a Python syntax error.",
        fix_description=(
            "1. Check for mismatched parentheses, brackets, or quotes.\n"
            "2. Check for incorrect indentation.\n"
            "3. Ensure all string literals are properly closed.\n"
            "4. Verify no markdown formatting (```python) leaked into the code."
        ),
        priority=10,
    ),

    ErrorPattern(
        id="name_error",
        name="Undefined variable or function",
        trigger_keywords=["NameError"],
        root_cause="A variable or function is used before being defined.",
        fix_description=(
            "1. Ensure all variables are defined before use.\n"
            "2. Check for typos in variable names.\n"
            "3. Make sure cadquery is imported: import cadquery as cq\n"
            "4. Verify all dimension variables are defined at the top of the script."
        ),
        priority=9,
    ),

    ErrorPattern(
        id="workplane_plane_arg",
        name="Wrong workplane plane specification",
        trigger_keywords=["TypeError"],
        trigger_any=["workplane", "Workplane"],
        root_cause=(
            ".workplane() does NOT accept a plane name string — its first arg is `offset` (float). "
            "Passing a plane name like .workplane('YZ') or .workplane('XZ', offset=10) raises TypeError. "
            "This commonly happens when trying to drill radial holes, add side features, or work "
            "on a non-XY plane."
        ),
        fix_description=(
            "To work on a non-default plane, use ONE of these approaches:\n"
            "1. Start a new chain on a named plane:\n"
            "   side_feature = cq.Workplane('YZ').circle(r).extrude(depth)\n"
            "   result = main_body.cut(side_feature)\n"
            "2. Select an existing face and place a workplane on it:\n"
            "   result = body.faces('>X').workplane().circle(r).cutThruAll()\n"
            "3. Rotate the current workplane with .transformed():\n"
            "   result = body.faces('>Z').workplane().transformed(rotate=(90, 0, 0)).circle(r).cutThruAll()\n"
            "4. For radial holes at a specific height, combine face selection with workplane offset or\n"
            "   build the hole on a separate Workplane and use .cut():\n"
            "   hole = cq.Workplane('YZ').workplane(offset=-depth/2).center(0, z_height).circle(r).extrude(depth)\n"
            "   result = body.cut(hole)"
        ),
        code_before='.workplane("YZ", offset=10).circle(3).cutThruAll()  # TypeError — "YZ" is not a valid arg',
        code_after='.faces(">X").workplane().circle(3).cutThruAll()  # Select side face, then drill',
        priority=9,
    ),

    ErrorPattern(
        id="type_error_workplane",
        name="Type error on Workplane method",
        trigger_keywords=["TypeError"],
        trigger_any=["Workplane", "workplane", "cq."],
        root_cause="A CadQuery method was called with wrong argument types or wrong number of arguments.",
        fix_description=(
            "1. Check the CadQuery API for correct method signatures.\n"
            "2. Common mistakes:\n"
            "   - .rect(width, height) not .rect((width, height))\n"
            "   - .circle(radius) not .circle(diameter)\n"
            "   - .extrude(distance) takes a single number, not a tuple\n"
            "   - .translate((x, y, z)) takes a tuple, not three separate args\n"
            "   - .pushPoints([(x1,y1), (x2,y2)]) takes a list of tuples"
        ),
        priority=7,
    ),

    ErrorPattern(
        id="attribute_error_cq",
        name="Attribute error on CadQuery object",
        trigger_keywords=["AttributeError"],
        trigger_any=["Workplane", "cq.", "Shape"],
        root_cause="Called a method that doesn't exist on the CadQuery object.",
        fix_description=(
            "1. Common confusions:\n"
            "   - Use .cut() not .subtract() or .difference()\n"
            "   - Use .union() not .add() or .join()\n"
            "   - Use .intersect() not .intersection()\n"
            "   - Use .translate() not .move() or .offset()\n"
            "   - Use .rotate() not .rotateAboutCenter() (that's for Workplane only)\n"
            "   - Use .faces() not .face() (plural)\n"
            "   - Use .edges() not .edge() (plural)\n"
            "2. Check if you're calling a Workplane method on a Shape or vice versa.\n"
            "3. After .val(), you have a Shape/Solid — use Shape methods, not Workplane methods."
        ),
        priority=7,
    ),

    ErrorPattern(
        id="sweep_degenerate_solid",
        name="Sweep produces zero-volume or degenerate solid",
        trigger_keywords=["sweep"],
        trigger_any=["Volume", "volume", "degenerate", "empty", "BRep_API", "TopoDS_Solid",
                      "Standard_NullObject", "zero"],
        root_cause=(
            "Sweeping a profile along an arc path can produce a degenerate (zero-volume) "
            "solid when: (1) the radiusArc sign is wrong, causing the path to curve in an "
            "unexpected direction; (2) you swept a pre-cut annular (ring) profile instead "
            "of sweeping outer and inner circles separately; or (3) the path self-intersects "
            "or the profile is too large relative to the bend radius."
        ),
        fix_description=(
            "1. For HOLLOW swept shapes (pipes, tubes): sweep the outer profile and inner "
            "profile SEPARATELY along the same path, then .cut() inner from outer.\n"
            "   outer = cq.Workplane('XY').circle(outer_r).sweep(path)\n"
            "   inner = cq.Workplane('XY').circle(inner_r).sweep(path)\n"
            "   result = outer.cut(inner)\n"
            "2. Check radiusArc sign: on XZ workplane, positive radius typically curves "
            "toward +Z. Try flipping the sign if the arc goes the wrong way.\n"
            "3. Ensure the profile radius is smaller than the bend radius to avoid "
            "self-intersection (pipe_or < bend_r).\n"
            "4. Verify with result.val().Volume() > 0 and result.val().isValid()."
        ),
        code_before='ring = cq.Workplane("XY").circle(10).circle(8).sweep(path)  # annular sweep — often degenerate',
        code_after=(
            'outer = cq.Workplane("XY").circle(10).sweep(path)\n'
            'inner = cq.Workplane("XY").circle(8).sweep(path)\n'
            'result = outer.cut(inner)  # sweep separately, then boolean cut'
        ),
        priority=8,
    ),

    # ==================================================================
    # EXTENDED ERROR PATTERNS (KB2 Additions)
    # ==================================================================

    # === SKETCH API ERRORS ===

    ErrorPattern(
        id="sketch_fillet_preferred",
        name="Use sketch fillet instead of 3D edge fillet for rectangular profiles",
        trigger_keywords=["StdFail_NotDone"],
        trigger_any=["fillet", "edges"],
        root_cause=(
            "The 3D edge fillet failed on vertical extruded edges. "
            "The Sketch API .vertices().fillet(r) creates a 2D arc BEFORE extrusion "
            "and cannot trigger StdFail_NotDone."
        ),
        fix_description=(
            "PREFERRED FIX — use 2D sketch fillet before extrusion:\n"
            "  result = (\n"
            "      cq.Workplane('XY')\n"
            "      .sketch().rect(80, 40).vertices().fillet(5).finalize()\n"
            "      .extrude(10)\n"
            "  )\n"
            "This operates on 2D geometry and NEVER fails.\n"
            "\n"
            "FALLBACK — if 3D fillet is required:\n"
            "  1. Reduce radius. Apply after ALL booleans and holes.\n"
            "  2. Use .edges('|Z') to target only vertical edges.\n"
            "  3. Wrap in try/except with pass."
        ),
        code_before="result = cq.Workplane('XY').box(80, 40, 10).edges('|Z').fillet(5)",
        code_after=(
            "result = (\n"
            "    cq.Workplane('XY')\n"
            "    .sketch().rect(80, 40).vertices().fillet(5).finalize()\n"
            "    .extrude(10)\n"
            ")"
        ),
        priority=11,
    ),

    ErrorPattern(
        id="sketch_finalize_missing",
        name="Sketch API: .finalize() not called before extrude",
        trigger_keywords=["AttributeError"],
        trigger_any=["finalize", "extrude", "sketch", "Sketch"],
        root_cause=(
            "After entering the Sketch API with .sketch(), the chain is in Sketch context. "
            ".extrude() does not exist on Sketch — it must be called after .finalize() "
            "to return to the Workplane context."
        ),
        fix_description=(
            "Add .finalize() before .extrude():\n"
            "  result = (\n"
            "      cq.Workplane('XY')\n"
            "      .sketch().rect(80, 40).vertices().fillet(5)\n"
            "      .finalize()    # ← REQUIRED\n"
            "      .extrude(10)\n"
            "  )"
        ),
        code_before=(
            "cq.Workplane('XY').sketch().rect(80, 40).vertices().fillet(5).extrude(10)"
        ),
        code_after=(
            "cq.Workplane('XY').sketch().rect(80, 40).vertices().fillet(5).finalize().extrude(10)"
        ),
        priority=10,
    ),

    # === FILLET — ADDITIONAL ===

    ErrorPattern(
        id="fillet_on_hole_rim",
        name="Fillet on circular hole rim fails — use chamfer instead",
        trigger_keywords=["StdFail_NotDone"],
        trigger_any=["%Circle", "circle", "hole", "bore", "rim"],
        root_cause=(
            "Applying .fillet() to a circular hole rim (the top edge of a drilled hole). "
            "OCCT's fillet kernel is unreliable on small-radius curved edges."
        ),
        fix_description=(
            "1. Use chamfer instead of fillet on circular hole rims:\n"
            "   result.faces('>Z').edges('%Circle').chamfer(0.5)\n"
            "2. Or use a countersink (.cskHole()) instead of post-hoc fillet for deburring:\n"
            "   .cskHole(6.4, 10, 82)  # M6 with 82° countersink\n"
            "3. Reduce fillet radius to ≤ 0.3× the hole radius.\n"
            "4. Wrap in try/except — skip if it fails."
        ),
        code_before="result.faces('>Z').edges('%Circle').fillet(2)",
        code_after=(
            "try:\n"
            "    result = result.faces('>Z').edges('%Circle').chamfer(0.5)\n"
            "except Exception:\n"
            "    pass  # skip edge break if geometry too tight"
        ),
        priority=9,
    ),

    # === BOOLEAN — ADDITIONAL ===

    ErrorPattern(
        id="cut_no_overlap",
        name="Cut produces no change — tool does not overlap base",
        trigger_keywords=["ValueError"],
        trigger_any=["cut", "empty", "Volume", "no overlap"],
        root_cause=(
            "The .cut() tool solid does not overlap with the base solid. "
            "Commonly caused by: wrong workplane origin, centered=True/False mismatch, "
            "or translate() moving the tool to the wrong position."
        ),
        fix_description=(
            "1. Print both bounding boxes before cutting:\n"
            "   print('Base:', base.val().BoundingBox().xmin, base.val().BoundingBox().xmax)\n"
            "   print('Tool:', tool.val().BoundingBox().xmin, tool.val().BoundingBox().xmax)\n"
            "   They must overlap in all 3 axes.\n"
            "2. box(80,40,5) with centered=True spans x=[-40,40] y=[-20,20] z=[-2.5,2.5].\n"
            "3. Make the tool 10% larger than needed in the cutting direction.\n"
            "4. Use .cutThruAll() to avoid needing to size the tool in depth."
        ),
        priority=7,
    ),

    # === FACE SELECTION — ADDITIONAL ===

    ErrorPattern(
        id="face_changed_after_boolean",
        name="Face selector selects wrong face after boolean operation",
        trigger_keywords=["IndexError"],
        trigger_any=["faces", ">Z", "<Z", ">X", "face"],
        root_cause=(
            "After .cut() or .union(), face geometry changes. A selector like .faces('>Z') "
            "may now select a different face because new faces were created at cut boundaries."
        ),
        fix_description=(
            "1. Use .tag() to save the face reference BEFORE the boolean:\n"
            "   base.faces('>Z').tag('top_face').workplane().hole(6)\n"
            "   result = base.cut(slot)\n"
            "   result = result.workplaneFromTagged('top_face').hole(4)\n"
            "2. Or use AreaNthSelector after boolean:\n"
            "   from cadquery import selectors\n"
            "   result.faces(selectors.AreaNthSelector(-1))  # largest face"
        ),
        code_before=(
            "result = base.cut(slot)\n"
            "result = result.faces('>Z').workplane().hole(5)  # >Z may be wrong face now"
        ),
        code_after=(
            "result = base.faces('>Z').tag('top').workplane().hole(5)\n"
            "result = result.end().cut(slot)  # boolean after tagging"
        ),
        priority=8,
    ),

    ErrorPattern(
        id="workplane_invert_needed",
        name="Feature appears on wrong side — invert=True needed",
        trigger_keywords=["workplane"],
        trigger_any=["wrong side", "inside", "outside", "direction", "invert"],
        root_cause=(
            "When selecting a face whose normal points INTO the part (bottom face, inside of hollow body), "
            "the workplane normal points the wrong way. Operations go in the wrong direction."
        ),
        fix_description=(
            "Add invert=True to .workplane():\n"
            "  result.faces('<Z').workplane(invert=True).hole(5)\n"
            "Use invert=True when working on:\n"
            "  - Bottom faces (normal points down)\n"
            "  - Inside faces of hollow bodies\n"
            "Rule: if feature appears on the OUTSIDE when you expected INSIDE, add invert=True."
        ),
        code_before=".faces('<Z').workplane().hole(5)",
        code_after=".faces('<Z').workplane(invert=True).hole(5)",
        priority=7,
    ),

    # === POLAR ARRAY — ADDITIONAL ===

    ErrorPattern(
        id="polar_array_uses_diameter",
        name="polarArray passed diameter instead of radius",
        trigger_keywords=["polarArray"],
        trigger_any=["radius", "diameter", "PCD", "pitch", "circle", "too far"],
        root_cause=(
            "polarArray(radius, ...) takes RADIUS as first argument, NOT diameter. "
            "If bolt PCD is 70mm, use radius=35, not radius=70."
        ),
        fix_description=(
            "ALWAYS use radius = PCD / 2:\n"
            "  .polarArray(pcd / 2, 0, 360, n_bolts)  # radius = half of pitch circle diameter\n"
            "\n"
            "Quick check: if holes appear twice as far from center as expected, divide first arg by 2."
        ),
        code_before=".polarArray(70, 0, 360, 6).hole(9)  # WRONG: 70 is PCD diameter",
        code_after=".polarArray(35, 0, 360, 6).hole(9)   # CORRECT: 35 = PCD/2",
        priority=10,
    ),

    # === PUSHPOINTS — ADDITIONAL ===

    ErrorPattern(
        id="pushpoints_global_vs_local",
        name="pushPoints coordinates in global space instead of workplane-local",
        trigger_keywords=["pushPoints"],
        trigger_any=["hole", "position", "wrong", "location", "coordinates"],
        root_cause=(
            "pushPoints([(x,y)]) coordinates are WORKPLANE-LOCAL, not global 3D. "
            "On .faces('>Z').workplane(), origin is at the CENTER of the top face. "
            "For an 80×40mm box, holes 60mm apart are at (-30,0) and (30,0), "
            "NOT at absolute global positions."
        ),
        fix_description=(
            "Workplane coordinates: (0,0) = center of the selected face.\n"
            "For holes 60mm apart on an 80×40mm bracket:\n"
            "  .pushPoints([(-30, 0), (30, 0)])  # ±30mm from face center\n"
            "  NOT [(-40, 0), (40, 0)]  # those are at the edges\n"
            "\n"
            "DEBUG: print the workplane origin:\n"
            "  wp = result.faces('>Z').workplane()\n"
            "  print('WP origin:', wp.plane.origin)"
        ),
        code_before=(
            "# WRONG: using global X positions (±40 = box edges)\n"
            "result.faces('>Z').workplane().pushPoints([(-40, 0), (40, 0)]).hole(6.4)"
        ),
        code_after=(
            "# CORRECT: 60mm apart = ±30mm from face center\n"
            "result.faces('>Z').workplane().pushPoints([(-30, 0), (30, 0)]).hole(6.4)"
        ),
        priority=9,
    ),

    # === SHELL — ADDITIONAL ===

    ErrorPattern(
        id="shell_opens_wrong_face",
        name="Shell opens wrong face (or no face selected before shell)",
        trigger_keywords=["shell"],
        trigger_any=["wrong", "closed", "no opening", "all faces"],
        root_cause=(
            "The face to REMOVE must be selected BEFORE calling .shell(). "
            "Without selection, ALL faces are shelled → closed hollow body (no opening). "
            "With wrong face selected → wrong opening."
        ),
        fix_description=(
            "To open the TOP face and shell inward:\n"
            "  result.faces('>Z').shell(-t)   # removes top face, shells 5 remaining\n"
            "\n"
            "To create a CLOSED hollow shell (ping-pong ball):\n"
            "  result.shell(-t)               # no face selection = all faces shelled\n"
            "\n"
            "IMPORTANT: shell negative = inward (preserves outer dims). Shell BEFORE fillet."
        ),
        code_before=(
            "result = cq.Workplane('XY').box(50, 50, 30).shell(-2)  # creates CLOSED hollow box"
        ),
        code_after=(
            "result = cq.Workplane('XY').box(50, 50, 30).faces('>Z').shell(-2)  # open-top box"
        ),
        priority=8,
    ),

    ErrorPattern(
        id="shell_after_fillet",
        name="Shell fails because fillet was applied first",
        trigger_keywords=["StdFail_NotDone"],
        trigger_any=["shell", "fillet"],
        root_cause=(
            "Applying .fillet() before .shell() creates complex curved faces that the "
            "OCCT shell kernel cannot offset cleanly."
        ),
        fix_description=(
            "Apply operations in this order: shell THEN fillet (never fillet then shell):\n"
            "  result = box.faces('>Z').shell(-t)   # 1. shell first\n"
            "  result = result.edges('|Z').fillet(r) # 2. fillet after"
        ),
        priority=8,
    ),

    # === CENTERED / POSITION ERRORS ===

    ErrorPattern(
        id="centered_box_z",
        name="Box floating above workplane — centered Z confusion",
        trigger_keywords=["box"],
        trigger_any=["centered", "floating", "position", "z", "above"],
        root_cause=(
            "cq.Workplane('XY').box(L, W, H) with default centered=True places box center at z=0, "
            "so it spans z=[-H/2, +H/2]. To sit ON the XY plane (base at z=0), use centered=(True,True,False)."
        ),
        fix_description=(
            "To place box BASE at z=0 (sitting on the XY plane):\n"
            "  cq.Workplane('XY').box(L, W, H, centered=(True, True, False))\n"
            "  → box spans z=[0, H]\n"
            "\n"
            "Or translate after creation:\n"
            "  cq.Workplane('XY').box(L, W, H).translate((0, 0, H/2))"
        ),
        priority=6,
    ),

    # === GEOMETRY VALIDATION ===

    ErrorPattern(
        id="invalid_solid_after_boolean",
        name="Shape.isValid() returns False after boolean",
        trigger_keywords=["isValid"],
        trigger_any=["False", "invalid", "defect"],
        root_cause=(
            "A boolean operation produced a geometrically invalid solid — "
            "near-coincident faces, tangent surfaces, or very thin slivers."
        ),
        fix_description=(
            "1. Use fuzzy boolean: .cut(tool, tol=1e-3)\n"
            "2. Offset tool by 0.001mm: tool = tool.translate((0, 0, 0.001))\n"
            "3. Pass clean=False: .cut(tool, clean=False)\n"
            "4. Call .clean() separately after boolean."
        ),
        priority=8,
    ),

    ErrorPattern(
        id="zero_volume_solid",
        name="Solid has near-zero volume",
        trigger_keywords=["Volume"],
        trigger_any=["0.0", "zero", "empty", "degenerate"],
        root_cause=(
            "Solid has near-zero volume: boolean removed all material, "
            "revolve produced a surface, or unclosed wire created a face instead of solid."
        ),
        fix_description=(
            "1. Check wire is closed: add .close() before .extrude().\n"
            "2. For revolve: ensure profile is a CLOSED wire.\n"
            "3. For swept hollow: sweep outer and inner SEPARATELY then .cut() inner from outer.\n"
            "4. After boolean: verify tool only partially overlaps base."
        ),
        priority=9,
    ),

    # === REVOLVE — ADDITIONAL ===

    ErrorPattern(
        id="revolve_wrong_plane",
        name="Revolved solid appears as flat disc — wrong workplane",
        trigger_keywords=["revolve"],
        trigger_any=["flat", "disc", "wrong", "missing", "height"],
        root_cause=(
            "For a solid of revolution, the profile must be on a workplane CONTAINING "
            "the revolution axis. Profile on XY plane revolving around Z gives a disc, not a vase."
        ),
        fix_description=(
            "Revolve around Y axis — use XZ workplane, profile at x > 0:\n"
            "  result = (\n"
            "      cq.Workplane('XZ')\n"
            "      .moveTo(5, 0)     # start at x=5 (radius), z=0 (base)\n"
            "      .lineTo(15, 0)    # outer base\n"
            "      .lineTo(15, 30)   # outer wall\n"
            "      .lineTo(5, 35)    # top taper\n"
            "      .close()\n"
            "      .revolve(360, (0,0,0), (0,1,0))  # revolve around Y\n"
            "  )"
        ),
        code_before=(
            "# WRONG: profile on XY, revolve around Z gives disc\n"
            "result = cq.Workplane('XY').rect(10, 30).revolve()"
        ),
        code_after=(
            "# CORRECT: profile on XZ, revolve around Y gives vase\n"
            "result = (\n"
            "    cq.Workplane('XZ')\n"
            "    .moveTo(5, 0).lineTo(15, 0).lineTo(15, 30).lineTo(5, 35).close()\n"
            "    .revolve(360, (0,0,0), (0,1,0))\n"
            ")"
        ),
        priority=8,
    ),

    # === SWEEP — ADDITIONAL ===

    ErrorPattern(
        id="sweep_wrong_profile_plane",
        name="Sweep profile on wrong workplane (not perpendicular to path start)",
        trigger_keywords=["sweep"],
        trigger_any=["tangent", "perpendicular", "BRep_API", "StdFail", "profile"],
        root_cause=(
            "The profile workplane must be perpendicular to the path start tangent. "
            "If path starts going along X (on XZ), profile must be on YZ plane."
        ),
        fix_description=(
            "Path start direction → required profile workplane:\n"
            "  Path along X (on XZ plane) → profile on 'YZ'\n"
            "  Path along Z (on XY plane) → profile on 'XY'\n"
            "  Path along Y (on YZ plane) → profile on 'XZ'\n"
            "\n"
            "For pipe elbow on XZ plane:\n"
            "  path = cq.Workplane('XZ').radiusArc((40, 40), 40)\n"
            "  outer = cq.Workplane('YZ').circle(pipe_or).sweep(path)\n"
            "  inner = cq.Workplane('YZ').circle(pipe_ir).sweep(path)\n"
            "  result = outer.cut(inner)"
        ),
        priority=8,
    ),

    # === PERFORMANCE ===

    ErrorPattern(
        id="helix_too_many_points",
        name="Helix/spring too slow (too many spline points)",
        trigger_keywords=["timeout"],
        trigger_any=["helix", "spring", "coil", "spline", "points"],
        root_cause=(
            "Generating a helix with 360+ spline points per turn is extremely slow. "
            "Each point adds to the OCCT BSpline computation."
        ),
        fix_description=(
            "Reduce to 36 points per turn (every 10° — smooth enough):\n"
            "  import math\n"
            "  pts_per_turn = 36  # NOT 360\n"
            "  n_turns = 5\n"
            "  pts = []\n"
            "  for i in range(pts_per_turn * n_turns + 1):\n"
            "      a = math.radians(i * 360 / pts_per_turn)\n"
            "      pts.append((r*math.cos(a), r*math.sin(a), i*pitch/pts_per_turn))\n"
            "  path = cq.Workplane('XY').spline(pts)\n"
            "  result = cq.Workplane('YZ').circle(wire_r).sweep(path)"
        ),
        priority=8,
    ),

    # === IMPORT ERRORS — ADDITIONAL ===

    ErrorPattern(
        id="cq_warehouse_not_available",
        name="cq_warehouse or other CadQuery plugin not available",
        trigger_keywords=["ModuleNotFoundError"],
        trigger_any=["cq_warehouse", "cadquery_massembly", "cq_gears"],
        root_cause=(
            "Optional CadQuery plugin imported but not installed: cq_warehouse, cq_gears, etc."
        ),
        fix_description=(
            "1. Remove cq_warehouse import. Implement natively.\n"
            "2. For threads: use smooth bore at tap diameter.\n"
            "   M6 tap = 5.0mm: result.faces('>Z').workplane().hole(5.0)\n"
            "3. Only safe imports: cadquery (cq), math, numpy."
        ),
        priority=10,
    ),

]


# ---------------------------------------------------------------------------
# Pattern matcher
# ---------------------------------------------------------------------------

def match_error(traceback_text: str) -> list[ErrorPattern]:
    """Match an error traceback against known patterns.

    Returns matching patterns sorted by priority (highest first).
    Typically 1-3 patterns match; the Error Refiner gets all of them.
    """
    matches = []
    tb_lower = traceback_text.lower()
    tb_original = traceback_text

    for pattern in PATTERNS:
        # All trigger_keywords must appear (case-insensitive)
        all_present = all(kw.lower() in tb_lower for kw in pattern.trigger_keywords)
        if not all_present:
            continue

        # If trigger_any is specified, at least one must appear
        if pattern.trigger_any:
            any_present = any(kw.lower() in tb_lower for kw in pattern.trigger_any)
            if not any_present:
                continue

        matches.append(pattern)

    # Sort by priority descending
    matches.sort(key=lambda p: p.priority, reverse=True)
    return matches


def format_matches_for_prompt(matches: list[ErrorPattern], max_patterns: int = 3) -> str:
    """Format matched patterns as context for the Error Refiner prompt."""
    if not matches:
        return ""

    lines = ["KNOWN ERROR PATTERNS (from AutoFab knowledge base):\n"]

    for i, pattern in enumerate(matches[:max_patterns]):
        lines.append(f"--- Pattern {i+1}: {pattern.name} ---")
        lines.append(f"Root cause: {pattern.root_cause}")
        lines.append(f"How to fix:\n{pattern.fix_description}")
        if pattern.code_before:
            lines.append(f"\nExample BAD code:\n  {pattern.code_before}")
        if pattern.code_after:
            lines.append(f"Example FIXED code:\n  {pattern.code_after}")
        lines.append("")

    return "\n".join(lines)


def get_error_context(traceback_text: str) -> str:
    """One-call convenience: match traceback and return formatted context.

    Returns empty string if no patterns match.
    """
    matches = match_error(traceback_text)
    return format_matches_for_prompt(matches)
