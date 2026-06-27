"""
merge.py — deterministic assembly of child sub-plans into one GeometryPlan.

This is the bookkeeping half of recursive decomposition (skills/assembly.md): the
PARENT agent reasons about WHICH parts exist and HOW they connect; this helper does
the single-right-answer mechanics it should not do by hand — namespacing step names,
rewiring intra-part `attach` references, renumbering sequence_ids, tagging parts, and
applying the cross-part connections the parent specifies.

It is pure Python (no CadQuery) and has exactly one correct output for a given input,
which is why it is deterministic and not a bandage: a model doing this by hand reliably
drops a reference or mis-numbers a step. The geometry underneath still flows through the
deterministic kernel mate system; this only stitches plans.
"""

import copy


def _ns(part, name, seq):
    """Namespace a step name so names stay unique after merge (and survive renumbering,
    unlike integer sequence_ids — which is why cross-part mates must reference names)."""
    return f"{part}.{name}" if name else f"{part}.s{seq}"


def merge_subplans(parts, connections=None, assembly_kind="single_solid", title=None):
    """Merge child sub-plans into one GeometryPlan dict.

    Args:
      parts: list of {"name": str, "plan": <subplan dict with primitives_sequence>}.
      connections: optional list describing how parts mate, each:
        {"from": "<part>" | "<part>.<step>", "to": "<part>" | "<part>.<step>",
         "at": <anchor>, "my_anchor"?: <anchor>, "gap"?: float, "offset"?: [x,y,z]}.
        A bare "<part>" resolves to that part's seed (its first step).
      assembly_kind: "single_solid" (fuse) or "assembly" (keep parts separate).
      title: optional plan title.

    Returns a GeometryPlan-shaped dict. overall_dimensions is a PROVISIONAL max-extent
    estimate (flagged in assumptions) — the agent reconciles it against the measured
    bbox after build_verify_render.
    """
    if not parts or not isinstance(parts, list):
        raise ValueError("parts must be a non-empty list of {'name','plan'}")

    merged_steps = []
    part_seed = {}
    eng = {"functional": [], "environmental_thermal": [], "structural": [], "manufacturing_cost": []}
    assumptions, clarifications, seen_clar, dims = [], [], set(), []

    for p in parts:
        pname = p.get("name")
        plan = p.get("plan") or {}
        if not pname or not isinstance(plan, dict):
            raise ValueError("each part needs a 'name' and a 'plan' dict")
        steps = copy.deepcopy(plan.get("primitives_sequence") or [])
        if not steps:
            raise ValueError(f"part {pname!r} has no primitives_sequence")
        ordered = sorted(steps, key=lambda s: s.get("sequence_id", 0))

        newnames = {id(s): _ns(pname, s.get("name"), s.get("sequence_id")) for s in ordered}
        local = {}
        for s in ordered:
            local[s.get("name")] = newnames[id(s)]
            local[s.get("sequence_id")] = newnames[id(s)]
        for i, s in enumerate(ordered):
            s["name"] = newnames[id(s)]
            s["part"] = pname
            att = s.get("attach")
            if att and att.get("to") is not None and att["to"] in local:
                att["to"] = local[att["to"]]
            if i == 0:
                part_seed[pname] = s["name"]
            merged_steps.append(s)

        er = plan.get("engineering_requirements") or {}
        for k in eng:
            for v in (er.get(k) or []):
                if v not in eng[k]:
                    eng[k].append(v)
        for a in (plan.get("assumptions") or []):
            if a not in assumptions:
                assumptions.append(a)
        for c in (plan.get("clarifications") or []):
            key = (c.get("question"), c.get("answer"))
            if key not in seen_clar:
                seen_clar.add(key)
                clarifications.append(c)
        if plan.get("overall_dimensions"):
            dims.append(plan["overall_dimensions"])

    for i, s in enumerate(merged_steps, start=1):
        s["sequence_id"] = i

    # single_solid = ONE fused, connected body: only the very first step seeds it; every other
    # 'new' (which would .add a separate body) must fuse. Parts are mated to touch via
    # `connections`, so converting to 'join' yields one connected component. (assembly keeps
    # parts separate, so operations are left untouched.)
    if assembly_kind == "single_solid":
        for s in merged_steps[1:]:
            if s.get("operation", "new") == "new":
                s["operation"] = "join"

    name_index = {s["name"]: s for s in merged_steps}

    def resolve_ref(ref):
        if ref in name_index:
            return ref
        if ref in part_seed:
            return part_seed[ref]
        return ref  # assume already namespaced

    for conn in (connections or []):
        frm = resolve_ref(conn.get("from"))
        to = resolve_ref(conn.get("to"))
        st = name_index.get(frm)
        if st is None:
            raise ValueError(f"connection 'from' {conn.get('from')!r} did not resolve to a step")
        if to not in name_index:
            raise ValueError(f"connection 'to' {conn.get('to')!r} did not resolve to a step")
        att = {"to": to, "at": conn.get("at", "top")}
        if conn.get("my_anchor"):
            att["my_anchor"] = conn["my_anchor"]
        if conn.get("gap") is not None:
            att["gap"] = conn["gap"]
        if conn.get("offset") is not None:
            att["offset"] = conn["offset"]
        st["attach"] = att

    if dims:
        ow = max(d.get("width", 0) for d in dims)
        ol = max(d.get("length", 0) for d in dims)
        oh = max(d.get("height", 0) for d in dims)
    else:
        ow = ol = oh = 0.0
    assumptions.append("overall_dimensions are a provisional merge estimate; reconcile against "
                       "the measured bbox after build_verify_render.")

    return {
        "title": title or f"{parts[0]['name']} assembly",
        "assembly_kind": assembly_kind,
        "overall_dimensions": {"width": ow, "length": ol, "height": oh},
        "engineering_requirements": eng,
        "assumptions": assumptions,
        "clarifications": clarifications,
        "primitives_sequence": merged_steps,
        "contains_freeform": any(s.get("primitive_type") == "custom" for s in merged_steps),
    }
