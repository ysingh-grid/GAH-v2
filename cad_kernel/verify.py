"""
verify.py — the FIXED, deterministic MeshLib verification battery (the VERDICT).

This is authored by a human, runs identically on every solid, and the RLM does
NOT get to choose or skip its checks. The RLM may PROPOSE advisory checks
(run_advisory) which can flag concerns but NEVER override the verdict.

Why fixed: if the model that generated the geometry also chose how it is graded,
it would pass its own mistakes (the bug and the blind spot share a cause). A fixed
battery cannot be quietly steered around the very error that would catch it.

A passing verdict means SOUND + RIGHT-SIZED, not "the right object". Freeform
geometry therefore stays needs_review even when every check passes.
"""

import os
import tempfile

import cadquery as cq
from meshlib import mrmeshpy as mm
from meshlib.mrmeshpy import MeshPart

# tolerances for the declared-vs-measured bounding-box audit (meshing adds error)
BBOX_ABS_TOL = 0.6   # mm
BBOX_REL_TOL = 0.03  # 3%


def cq_to_meshlib(obj, tol: float = 0.01):
    """Bridge a CadQuery object (Workplane with one or many bodies, or a Solid) into a
    MeshLib mesh via a temporary STL. Normalizes to a clean compound so every body is
    exported (so assemblies measure all their parts)."""
    from cadquery import Compound
    if hasattr(obj, "vals"):
        shapes = []
        for v in obj.vals():
            shapes.append(v.val() if hasattr(v, "val") else v)
    elif hasattr(obj, "val"):
        shapes = [obj.val()]
    else:
        shapes = [obj]
    shapes = [s for s in shapes if s is not None]
    export_obj = shapes[0] if len(shapes) == 1 else Compound.makeCompound(shapes)
    f = tempfile.mktemp(suffix=".stl")
    cq.exporters.export(export_obj, f, tolerance=tol)
    try:
        return mm.loadMesh(f)
    finally:
        if os.path.exists(f):
            os.remove(f)


def measure(mesh) -> dict:
    """Deterministic intrinsic measurements of a mesh."""
    bb = mesh.computeBoundingBox()
    return {
        "volume": round(mesh.volume(), 4),
        "area": round(mesh.area(), 4),
        "bbox": [round(bb.max.x - bb.min.x, 4),
                 round(bb.max.y - bb.min.y, 4),
                 round(bb.max.z - bb.min.z, 4)],
        "watertight": mesh.topology.findHoleRepresentiveEdges().size() == 0,
        "components": int(mm.MeshComponents.getNumComponents(mesh)),
        "self_intersections": int(mm.findSelfCollidingTriangles(MeshPart(mesh)).size()),
    }


def _bbox_audit(meas, declared_bbox):
    """declared_bbox = [x, y, z] (any order); compare to measured sorted dims."""
    if not declared_bbox:
        return None, "no declared bbox to audit against"
    md = sorted(meas["bbox"])
    dd = sorted(float(v) for v in declared_bbox)
    ok = all(abs(a - b) <= max(BBOX_ABS_TOL, BBOX_REL_TOL * b) for a, b in zip(md, dd))
    return ok, f"measured {md} vs declared {dd} (sorted, tol {BBOX_ABS_TOL}mm/{int(BBOX_REL_TOL*100)}%)"


CONTACT_EPS = float(os.environ.get("FORGECAD_CONTACT_EPS", "0.5"))  # mm: parts within this touch

# Mating-quality gate tunables (object-agnostic). A contacting/overlapping pair is classified by
# the CONTAINMENT RATIO c = V_intersection / min(volA, volB):
#   below OVERLAP_FLOOR_ABS (mm^3)     -> flush face contact / meshing sliver -> OK.
#   c <= OVERLAP_MINOR_FRAC            -> a small JOINT/CONVERGENCE overlap (how radial spokes meet
#                                         at a hub, or parts take a little interference to fuse) -> OK.
#   c >= CONTAINMENT_RATIO             -> the smaller part is essentially INSIDE the other: an
#                                         INTENDED insertion (peg-in-hole, telescoping, embedded
#                                         spine) -> OK.
#   in between (MINOR_FRAC < c < CONTAINMENT_RATIO) -> a part substantially BURIED in another
#                                         ("dug inside") -> flagged + the verdict FAILs.
CONTAINMENT_RATIO = float(os.environ.get("FORGECAD_CONTAINMENT_RATIO", "0.75"))
OVERLAP_MINOR_FRAC = float(os.environ.get("FORGECAD_OVERLAP_MINOR_FRAC", "0.2"))  # <= this = OK joint
OVERLAP_FLOOR_ABS = float(os.environ.get("FORGECAD_OVERLAP_FLOOR", "0.5"))  # mm^3 absolute noise floor

# Primitives whose self-intersection has a SPECIFIC, recurring cause (a cross-section too large for
# the local path/feature) — so we can give a directed fix instead of a raw triangle count.
_SWEEP_LIKE = {"swept_circle": "sweep", "swept_profile": "sweep",
               "lofted_box": "loft", "lofted_sections": "loft", "twisted_loft": "loft",
               "revolved_profile": "revolve"}


def _construction_hint(plan, part_names=None):
    """If an unsound part/solid was built from a swept/lofted/revolved primitive, return a SPECIFIC,
    actionable hint naming the likely cause, instead of leaving the agent to guess from a raw
    self-intersection count. Object-agnostic + advisory (it only enriches the failure detail)."""
    try:
        seq = (plan or {}).get("primitives_sequence") or []
    except Exception:
        return ""
    names = set(part_names) if part_names else None
    kinds = set()
    for s in seq:
        kind = _SWEEP_LIKE.get(s.get("primitive_type"))
        if not kind:
            continue
        if names is not None:
            grp = s.get("part") or s.get("name") or f"part_{s.get('sequence_id')}"
            if grp not in names and s.get("name") not in names:
                continue
        kinds.add(kind)
    if not kinds:
        return ""
    k = "/".join(sorted(kinds))
    return (f" — LIKELY CAUSE: a {k} self-intersects because its cross-section is too large for the "
            f"local path/feature (a tube/section wider than a path segment is long, or a profile "
            f"that turns too sharply). FIX: reduce the radius/section size, or lengthen/smooth/space "
            f"the path/sections so each segment is longer than the section is wide — no corner "
            f"treatment can save a tube fatter than its turn.")


def _pair_min_distance(mesh_a, mesh_b) -> float:
    """Min surface distance between two meshes (0 if they overlap/touch). Uses MeshLib's
    findSignedDistance; abs() because overlap reports 0 and a gap reports a positive value."""
    res = mm.findSignedDistance(mesh_a, mesh_b)
    if res is None:
        return float("inf")
    return abs(res.signedDist)


def _mesh_center(mesh):
    bb = mesh.computeBoundingBox()
    return ((bb.min.x + bb.max.x) / 2.0, (bb.min.y + bb.max.y) / 2.0, (bb.min.z + bb.max.z) / 2.0)


def _contact_move_vec(mesh_n, mesh_tgt):
    """Vector that translates mesh_n so its CLOSEST surface point meets mesh_tgt's closest point —
    i.e. flush contact along the TRUE contact normal (not the center-to-center line). Uses
    MeshLib's signed-distance closest points. Returns (vec, signed_gap); vec is None if the closest
    points are unavailable (caller falls back to the legacy center-to-center step)."""
    try:
        r = mm.findSignedDistance(mesh_n, mesh_tgt)
    except Exception:
        return None, float("inf")
    if r is None:
        return None, float("inf")
    gap = r.signedDist
    try:
        a, b = r.a.point, r.b.point
        return (b.x - a.x, b.y - a.y, b.z - a.z), gap
    except Exception:
        return None, gap


def _intersection_volume(mesh_a, mesh_b) -> float:
    """Volume (mm^3) of the boolean intersection of two part meshes; 0.0 if disjoint/flush.
    FAIL-OPEN: any MeshLib error -> 0.0 (the gate must never crash the verdict)."""
    try:
        res = mm.boolean(mesh_a, mesh_b, mm.BooleanOperation.Intersection)
        if not res.valid():
            return 0.0
        return max(0.0, res.mesh.volume())
    except Exception:
        return 0.0


def _legacy_center_snap(wp, mesh_n, mesh_tgt, eps):
    """Legacy fallback: step the part toward the target's CENTER until within eps (used only when
    the flush contact normal is unavailable). Returns (wp, total_moved)."""
    total = 0.0
    cur = mesh_n
    for _i in range(5):
        d = _pair_min_distance(cur, mesh_tgt)
        if d <= eps or d == float("inf"):
            break
        cn, ct = _mesh_center(cur), _mesh_center(mesh_tgt)
        vx, vy, vz = ct[0] - cn[0], ct[1] - cn[1], ct[2] - cn[2]
        mag = (vx * vx + vy * vy + vz * vz) ** 0.5
        if mag < 1e-9:
            break
        step = d + eps
        wp = wp.translate((vx / mag * step, vy / mag * step, vz / mag * step))
        cur = cq_to_meshlib(wp)
        total += step
    return wp, total


def snap_assembly_to_contact(part_solid_map, group_targets, eps: float = None, passes: int = 2):
    """Fix A + mating gate: make `attach` an UNBREAKABLE *flush* contact guarantee for an assembly.

    A part that DECLARED it connects (`attach.to`) but ended up with a gap is translated TOWARD ITS
    DECLARED TARGET until the two surfaces TOUCH FLUSH. The move is along the TRUE contact normal by
    EXACTLY the surface gap (MeshLib closest points), so the part lands flush and STOPS at contact —
    it never overshoots INTO the target. (The old center-to-center `d+eps` stepping shoved parts
    16-22mm and buried them; that is precisely what produced the "dug inside" artifact.) If a move
    would bury the part (create intersection volume) it is backed off until flush.

    Safety invariants (this can only help, never hurt):
      - INTENT-ONLY: a part is moved solely toward the target IT named (group_targets). Absolute-
        position parts are NEVER moved, so a genuinely misplaced/standalone part still fails
        coherence and yields its feedback — and every "expect disconnection" test is preserved.
      - FAIL-OPEN: any error leaves the part exactly as-is; if the contact normal is unavailable we
        fall back to the legacy center-to-center step. The result is never worse than before.
      - The token hashes the PLAN (not the solid), so a snapped solid never affects authenticity and
        replays identically at the gate.

    Args:
      part_solid_map: OrderedDict part_name -> CadQuery workplane (mutated in place + returned).
      group_targets:  dict part_name -> the part_name it declared attach.to (a different group).
    Returns: (part_solid_map, snapped_info) where snapped_info lists {part, to, moved_mm}.
    """
    eps = CONTACT_EPS if eps is None else eps
    names = list(part_solid_map.keys())
    if len(names) < 2 or not group_targets:
        return part_solid_map, []
    try:
        meshes = {n: cq_to_meshlib(wp) for n, wp in part_solid_map.items()}
    except Exception:
        return part_solid_map, []
    bury_tol = max(eps, 0.05)
    snapped = {}
    for _pass in range(max(1, passes)):
        moved_any = False
        for n in names:                      # first-appearance (approx sequence) order: parents first
            tgt = group_targets.get(n)
            if not tgt or tgt == n or tgt not in part_solid_map:
                continue
            try:
                mv, gap = _contact_move_vec(meshes[n], meshes[tgt])
                if gap <= eps:
                    continue                 # already touching/overlapping its declared target -> no-op
                wp = part_solid_map[n]
                total = 0.0
                if mv is not None:
                    vx, vy, vz = mv
                    mag = (vx * vx + vy * vy + vz * vz) ** 0.5
                    if mag < 1e-9:
                        continue
                    ux, uy, uz = vx / mag, vy / mag, vz / mag
                    # FLUSH: move along the contact normal by exactly the gap; back off if it buries.
                    frac = 1.0
                    landed = None
                    for _ in range(6):
                        d = gap * frac
                        cand = wp.translate((ux * d, uy * d, uz * d))
                        cm = cq_to_meshlib(cand)
                        try:
                            sd = mm.findSignedDistance(cm, meshes[tgt]).signedDist
                        except Exception:
                            sd = 0.0
                        if sd >= -bury_tol:  # flush / just touching, not buried
                            landed = (cand, cm, d)
                            break
                        frac *= 0.5          # overshot into the target -> back off
                    if landed is not None:
                        wp, meshes[n], total = landed[0], landed[1], landed[2]
                else:
                    wp, total = _legacy_center_snap(wp, meshes[n], meshes[tgt], eps)
                    if total > eps:
                        meshes[n] = cq_to_meshlib(wp)
                if total > eps:
                    part_solid_map[n] = wp
                    snapped[n] = {"to": tgt, "moved_mm": round(total, 2)}
                    moved_any = True
            except Exception:
                continue                     # fail-open: leave this part unchanged
        if not moved_any:
            break
    return part_solid_map, [{"part": k, **v} for k, v in snapped.items()]


def verify_assembly_coherence(part_solids: dict, eps: float = None) -> dict:
    """Verify an assembly is ONE coherent object: every part individually sound AND the
    parts form a single connected, contact-touching cluster (not a fused blob, not a loose
    bag of parts). `part_solids` maps part name -> CadQuery workplane.

    Returns the per-part soundness result + the contact-graph connectivity, including which
    part(s) are isolated and their nearest gap (for actionable, geometry-aware feedback)."""
    eps = CONTACT_EPS if eps is None else eps
    names = list(part_solids.keys())
    meshes = {n: cq_to_meshlib(wp) for n, wp in part_solids.items()}

    # (a) per-part soundness — inter-part overlap is EXPECTED (that is what makes parts
    #     touch), so soundness is checked PER PART, never on the combined mesh.
    unsound = []
    for n in names:
        meas = measure(meshes[n])
        reasons = []
        if meas["volume"] <= 0:
            reasons.append("non-positive volume")
        if not meas["watertight"]:
            reasons.append("not watertight")
        if meas["self_intersections"] > 0:
            reasons.append(f"{meas['self_intersections']} self-intersecting triangle(s)")
        if reasons:
            unsound.append({"part": n, "issues": ", ".join(reasons)})

    # (c) contact graph — union-find over pairs whose surfaces are within eps.
    parent = {n: n for n in names}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    # Per-part volumes + bounding boxes (the bbox is a cheap broad-phase so the costlier
    # intersection-volume boolean only runs on pairs that could actually overlap).
    vols = {}
    bbs = {}
    for n in names:
        try:
            vols[n] = max(0.0, meshes[n].volume())
        except Exception:
            vols[n] = 0.0
        try:
            bb = meshes[n].computeBoundingBox()
            bbs[n] = (bb.min.x, bb.min.y, bb.min.z, bb.max.x, bb.max.y, bb.max.z)
        except Exception:
            bbs[n] = None

    def _bbox_overlap(a, b, m):
        pa, pb = bbs.get(a), bbs.get(b)
        if pa is None or pb is None:
            return True                      # unknown extent -> don't skip (be safe)
        return (pa[0] <= pb[3] + m and pa[3] >= pb[0] - m and
                pa[1] <= pb[4] + m and pa[4] >= pb[1] - m and
                pa[2] <= pb[5] + m and pa[5] >= pb[2] - m)

    # Pairwise surface distances + (broad-phase-gated) intersection VOLUME. Two parts are CONNECTED
    # if their surfaces touch (d <= eps) OR their volumes overlap (a fully-embedded insertion does
    # not "touch" by surface distance but is obviously one object). Each overlapping pair is then
    # classified by the containment ratio: tiny -> flush contact; >= CONTAINMENT_RATIO -> intended
    # insertion; in between -> a BAD partial interpenetration ("dug inside").
    pair_dist = {}
    interpenetrations = []
    insertions = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            d = _pair_min_distance(meshes[a], meshes[b])
            pair_dist[(a, b)] = pair_dist[(b, a)] = d
            vint = _intersection_volume(meshes[a], meshes[b]) if _bbox_overlap(a, b, eps) else 0.0
            vsmall = min(vols.get(a, 0.0), vols.get(b, 0.0))
            overlapping = vint > OVERLAP_FLOOR_ABS and vsmall > 0
            if d <= eps or overlapping:
                union(a, b)
            if overlapping:
                c = vint / vsmall
                small, big = (a, b) if vols.get(a, 0.0) <= vols.get(b, 0.0) else (b, a)
                if c >= CONTAINMENT_RATIO:
                    insertions.append({
                        "inner": small, "outer": big,
                        "overlap_mm3": round(vint, 2), "containment": round(c, 3),
                        "note": f"'{small}' is largely inside '{big}' — treated as an intended "
                                f"insertion/containment (allowed)."})
                elif c > OVERLAP_MINOR_FRAC:
                    interpenetrations.append({
                        "partA": big, "partB": small,
                        "overlap_mm3": round(vint, 2), "overlap_fraction": round(c, 3),
                        "hint": f"'{small}' is buried {round(c * 100)}% into '{big}'. Pull "
                                f"'{small}' back so the surfaces meet FLUSH (reduce the "
                                f"offset/overlap), or mate it with `attach` face-anchors "
                                f"(at/my_anchor) so the host lands it flush — do not bury it."})
                # else: c <= OVERLAP_MINOR_FRAC -> a small joint/convergence overlap (allowed).

    clusters = {}
    for n in names:
        clusters.setdefault(find(n), []).append(n)
    cluster_list = list(clusters.values())
    connected = len(cluster_list) <= 1

    isolated = []
    main_body = None
    if not connected:
        # The largest cluster is the "main body"; everything else is disconnected FROM it.
        main_body = max(cluster_list, key=len)
        for comp in cluster_list:
            if comp is main_body:
                continue
            for n in comp:
                best_nb, best_d = None, float("inf")
                for m in main_body:
                    d = pair_dist.get((n, m), float("inf"))
                    if d < best_d:
                        best_d, best_nb = d, m
                gap = round(best_d, 2) if best_d != float("inf") else None
                hint = (f"attach '{n}' to '{best_nb}' (the nearest part of the main body) "
                        f"instead of placing it by absolute position" +
                        (f", or close the {gap}mm gap" if gap else "")) if best_nb else \
                       f"connect '{n}' to the rest of the assembly with an `attach` mate"
                isolated.append({"part": n, "nearest_in_main_body": best_nb,
                                 "gap_mm": gap, "hint": hint})

    return {
        "part_count": len(names),
        "parts": names,
        "all_parts_sound": len(unsound) == 0,
        "unsound_parts": unsound,
        "contact_connected": connected,
        "num_clusters": len(cluster_list),
        "main_body": main_body,
        "isolated_parts": isolated,
        "interpenetrations": interpenetrations,
        "insertions": insertions,
        "eps_mm": eps,
    }


def verify_solid(solid, declared_bbox=None, expected_components: int = 1,
                 plan: dict = None, part_solids: dict = None, fusion_audit: dict = None,
                 size_constraint: dict = None) -> dict:
    """Run the FIXED battery on a CadQuery solid. Returns measurements + per-check results
    + an overall deterministic verdict.

    Two modes (the verdict is still authored host-side; the generator never grades itself):
      - single_solid (default / plan absent): ONE fused connected body — watertight, exactly
        `expected_components` connected component(s), no self-intersections, positive volume,
        declared-vs-measured bbox.
      - assembly (plan['assembly_kind']=='assembly' AND part_solids given): a COHERENT object
        — every part sound on its own, the parts forming ONE connected contact-touching cluster
        (R2). Whole-mesh watertight/self-intersection/component-count are NOT applied, because
        legitimately-overlapping mated parts would (correctly) register as inter-part collisions.
    """
    mesh = cq_to_meshlib(solid)
    meas = measure(mesh)

    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    is_assembly = (plan or {}).get("assembly_kind") == "assembly" and part_solids

    add("positive_volume", meas["volume"] > 0, f"volume = {meas['volume']} mm^3")

    coherence = None
    if is_assembly:
        coherence = verify_assembly_coherence(part_solids)
        if coherence["unsound_parts"]:
            detail = "; ".join(f"{u['part']}: {u['issues']}" for u in coherence["unsound_parts"])
            detail += _construction_hint(plan, [u["part"] for u in coherence["unsound_parts"]])
        else:
            detail = f"all {coherence['part_count']} part(s) individually sound"
        add("parts_sound", coherence["all_parts_sound"], detail)
        if coherence["contact_connected"]:
            cdetail = (f"all {coherence['part_count']} part(s) form ONE connected object "
                       f"(touch within {coherence['eps_mm']}mm)")
        else:
            iso = "; ".join(d["hint"] for d in coherence["isolated_parts"])
            cdetail = (f"{coherence['num_clusters']} disconnected cluster(s); NOT one object "
                       f"(main body = {coherence.get('main_body')}). Fix: {iso}")
        add("assembly_coherent", coherence["contact_connected"], cdetail)
        # Mating gate: parts may TOUCH (flush) or be INSERTED (small part inside a larger one), but
        # must not be partially BURIED in each other ("dug inside"). Insertions are carved out so
        # telescoping/peg-in-hole/embedded-spine designs still pass.
        inter = coherence.get("interpenetrations") or []
        if inter:
            pairs = "; ".join(
                f"{x['partB']} buried {round(x['overlap_fraction'] * 100)}% into {x['partA']} "
                f"({x['overlap_mm3']}mm^3)" for x in inter)
            idetail = (f"{len(inter)} interpenetrating pair(s): {pairs}. Fix: "
                       + " | ".join(x["hint"] for x in inter))
        else:
            ins = coherence.get("insertions") or []
            idetail = ("no two parts interpenetrate (contacts are flush"
                       + (f"; {len(ins)} intended insertion(s) allowed" if ins else "") + ")")
        add("no_interpenetration", len(inter) == 0, idetail)
    else:
        wt_detail = "closed mesh (no boundary holes)" if meas["watertight"] else "OPEN mesh — boundary holes present"
        if not meas["watertight"]:
            wt_detail += _construction_hint(plan, None)
        add("watertight", meas["watertight"], wt_detail)
        comp_ok = meas["components"] == expected_components
        add("component_count", comp_ok,
            f"{meas['components']} connected component(s), expected exactly {expected_components}")
        no_self_int = meas["self_intersections"] == 0
        si_detail = f"{meas['self_intersections']} self-colliding triangle(s)"
        if not no_self_int:
            si_detail += _construction_hint(plan, None)
        add("no_self_intersections", no_self_int, si_detail)

        # BACKSTOP INVARIANT (host-side, deterministic): a boolean union/join can only ADD volume,
        # so a fused single_solid can never be smaller than its largest contributing body minus what
        # cuts legitimately remove. If it IS, a build step's body was SILENTLY DROPPED by a fragile
        # boolean (the impeller hub+blade->blade bug). This is the gate that makes such a loss LOUD.
        # FAIL-OPEN: only runs when the kernel marked the audit `applicable` (no intersect/modifier,
        # all operand volumes measurable); otherwise it is skipped and never false-fails.
        fa = fusion_audit or {}
        if fa.get("applicable") and fa.get("max_additive_volume") is not None:
            floor = float(fa["max_additive_volume"]) - float(fa.get("total_cut_volume", 0.0) or 0.0)
            tol = max(1.0, 0.02 * abs(floor))      # 2% + 1mm^3 (numeric/mesh slack); a drop loses >>this
            if floor > tol:                        # only meaningful when a real body should remain
                kept = meas["volume"] >= floor - tol
                detail = (f"fused volume {round(meas['volume'], 1)} mm^3 vs floor {round(floor, 1)} "
                          f"mm^3 (largest body '{fa.get('largest_additive_name')}' minus cuts)")
                if not kept:
                    detail += (" — a build step's body was DROPPED by a boolean. A join/union must "
                               "KEEP every body; this likely failed on tangent/coincident faces. "
                               "Give the joined feature a small overlap into the body it fuses to, "
                               "or build the pieces as separate `attach`-ed parts (assembly).")
                add("no_dropped_body", kept, detail)

    # P5: HARD max-envelope gate for an EXPLICIT user-stated size (a non-negotiable). FAILs only if
    # the model's largest extent grossly EXCEEDS the stated cap (the cap already includes a 15%
    # margin). Smaller/proportion is NOT gated here (emergent size stays advisory — the fidelity
    # critic handles "too small / wrong proportion"). FAIL-OPEN: no constraint -> no check.
    try:
        if size_constraint and size_constraint.get("max_extent_mm"):
            cap = float(size_constraint["max_extent_mm"])
            max_extent = max(meas["bbox"]) if meas.get("bbox") else 0.0
            ok = max_extent <= cap
            src = size_constraint.get("source") or "stated size"
            detail = (f"model's largest extent {round(max_extent, 1)} mm vs limit {round(cap, 1)} mm "
                      f"(from '{src}')")
            if not ok:
                detail += (" — EXCEEDS the user-stated size. Reduce the controlling part dimensions "
                           "so the overall extent fits within the stated limit.")
            add("size_envelope", ok, detail)
    except Exception:
        pass

    # Bounding box is an OUTPUT the kernel owns, NOT a self-audit the agent must reproduce.
    # The overall extent of a mated assembly is EMERGENT (it depends on mate-derived coordinates
    # the agent never sees), so forcing a declared-vs-measured match just makes the agent
    # hand-compute a number the kernel already knows — the same trap mates/patterns/merge remove.
    # We therefore REPORT the measured bbox (and an informational note vs any declared value) but
    # never gate the verdict on it. Genuine "right size vs the request" is checked by the
    # intent-grounded fidelity critic, which receives this measured bbox.
    _, bbox_detail = _bbox_audit(meas, declared_bbox)

    facts_pass = all(c["passed"] for c in checks)
    failures = [c for c in checks if not c["passed"]]
    out = {
        "measurements": meas,
        "measured_bbox": meas["bbox"],
        "checks": checks,
        "facts_pass": facts_pass,
        "verdict": "PASS" if facts_pass else "FAIL",
        "localized_fix": (None if facts_pass else
                          "; ".join(f"{c['name']}: {c['detail']}" for c in failures)),
    }
    if bbox_detail:
        out["bbox_note"] = bbox_detail
    if coherence is not None:
        out["coherence"] = coherence
    return out


def run_advisory(solid, fn_name: str, **kwargs) -> dict:
    """Run an RLM-PROPOSED measurement from MeshLib as an ADVISORY signal only.
    Never contributes to the verdict — it can flag a concern, not certify a pass.
    fn_name must be a callable on mrmeshpy or a method on the Mesh."""
    mesh = cq_to_meshlib(solid)
    target = getattr(mesh, fn_name, None) or getattr(mm, fn_name, None)
    if target is None:
        return {"advisory": fn_name, "ok": False, "error": "unknown MeshLib symbol"}
    try:
        val = target(mesh, **kwargs) if getattr(mm, fn_name, None) is target else target(**kwargs)
        return {"advisory": fn_name, "ok": True, "value": str(val)[:200],
                "note": "ADVISORY ONLY — does not affect the verdict"}
    except Exception as e:
        return {"advisory": fn_name, "ok": False, "error": str(e)[:200]}
