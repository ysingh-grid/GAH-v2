"""
fidelity.py — host-side VISION for "Thinking in 3D": design-brief extraction (input),
fidelity / design-review (judgment), and spatial critique (connectivity feedback).

A PASS from the geometric battery means SOUND + COHERENT, never "the right object" — and never
"a WELL-FORMED object". A model will happily game a purely-geometric gate into a blocky
placeholder. This module is where the (separate) vision model judges form, and where a
user-supplied REFERENCE image both guides planning (a text brief) and grounds the judgment.

Design invariants (kept across phases):
- The critic judges against the IMMUTABLE intent (user prompt + clarifier answers, from
  FORGECAD_INTENT) and, when available, a REFERENCE image (FORGECAD_REFERENCE_IMAGE). It never
  reads the agent's own mutable requirements.
- The generator never grades itself: the critic is a SEPARATE model role seeing only the
  render(s) (+ reference), not the agent's reasoning.
- FAIL-OPEN on infrastructure error (no key / network / timeout / parse) — degrade gracefully,
  never block or crash. FAIL-CLOSED only on a genuine "doesn't look right" verdict.
- Reference is OPTIONAL: with no reference image, critique falls back to the intent-only bar so
  CLI runs and tests are unaffected.

Verdict shape: {"status": "pass"|"reject"|"unavailable", "recognizable": bool,
                "present_features": [...], "missing_major_features": [...], "notes": str}
(missing_major_features doubles as the directive list: for the grounded reviewer it carries
refinement/orientation fixes like "seat is a flat slab — contour it".)
"""

import base64
import json
import os

VISION_MODEL_ENV = "FORGECAD_VISION_MODEL"
INTENT_ENV = "FORGECAD_INTENT"
REFERENCE_ENV = "FORGECAD_REFERENCE_IMAGE"     # path to the user's reference image (optional)
FORM_BRIEF_ENV = "FORGECAD_FORM_BRIEF"         # text form brief (used to STRENGTHEN the no-image bar)
STUB_ENV = "FORGECAD_FIDELITY_STUB"            # tests inject a JSON verdict here
SPATIAL_STUB_ENV = "FORGECAD_SPATIAL_STUB"     # tests inject a spatial-critique string here
BRIEF_STUB_ENV = "FORGECAD_BRIEF_STUB"         # tests inject a brief string here
TIMEOUT_S = float(os.environ.get("FORGECAD_FIDELITY_TIMEOUT", "60"))


# ---------------------------------------------------------------------------- helpers
def _resolve_intent(intent: str = None) -> str:
    """Explicit intent, else FORGECAD_INTENT (prompt + clarifier answers)."""
    if intent:
        return intent
    raw = os.environ.get(INTENT_ENV)
    if not raw:
        return ""
    try:
        obj = json.loads(raw)
        out = obj.get("prompt", "")
        for c in (obj.get("clarifications") or []):
            out += f"\n- {c.get('question','')} -> {c.get('answer','')}"
        return out
    except Exception:
        return raw


def _reference_image_path():
    """Path to the user's reference image, if one was provided and exists."""
    p = os.environ.get(REFERENCE_ENV)
    return p if (p and os.path.exists(p)) else None


def _img_block(path):
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}


def _vision_chat(system: str, user_content: list) -> str:
    """One host-side multimodal chat call. Returns the text reply, or raises on any error."""
    api_key = os.environ.get("RLM_MODEL_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    base_url = os.environ.get("RLM_MODEL_BASE_URL") or "https://openrouter.ai/api/v1"
    model = os.environ.get(VISION_MODEL_ENV) or "gemini-2.5-pro"
    if not api_key:
        raise RuntimeError("no RLM_MODEL_API_KEY")
    import httpx
    r = httpx.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "temperature": 0,
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user_content}]},
        timeout=TIMEOUT_S)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"] or ""


def _extract_json(text: str) -> dict:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if "```" in t[3:] else t.strip("`")
        if t.lstrip().startswith("json"):
            t = t.lstrip()[4:]
    s, e = t.find("{"), t.rfind("}")
    if s == -1 or e == -1:
        raise ValueError("no JSON object in critic response")
    return json.loads(t[s:e + 1])


def _feature_to_str(f) -> str:
    """Flatten a feedback item to a single string. Accepts a plain string OR a structured
    {part?, issue|feature, fix?} dict (B3), so the critic can return per-part directives while
    every existing string-list consumer keeps working."""
    if isinstance(f, dict):
        part = f.get("part") or ""
        issue = f.get("issue") or f.get("feature") or f.get("problem") or ""
        fix = f.get("fix") or f.get("suggestion") or ""
        s = (f"{part}: " if part else "") + str(issue)
        if fix:
            s += f" -> {fix}"
        return s.strip(" :->")
    return str(f)


def _verdict_from_payload(d: dict) -> dict:
    recognizable = bool(d.get("recognizable", False))
    raw_missing = d.get("missing_major_features") or []
    missing = [_feature_to_str(f) for f in raw_missing]
    return {
        "status": "pass" if (recognizable and not raw_missing) else "reject",
        "recognizable": recognizable,
        "present_features": d.get("present_features") or [],
        # back-compat: always a list[str] for existing consumers (geometry_server next_action join)
        "missing_major_features": missing,
        # B3: preserve the structured form (list of dicts) when the critic provided it
        "missing_features_structured": raw_missing,
        "notes": str(d.get("notes", ""))[:400],
    }


def _unavailable(reason: str) -> dict:
    return {"status": "unavailable", "recognizable": None, "present_features": [],
            "missing_major_features": [], "notes": f"fidelity_unavailable: {reason}"}


# ---------------------------------------------------------------------------- prompts
_SYSTEM_INTENT_ONLY = (
    "You are a critical CAD design reviewer. You are shown rendered multi-view images of a 3D "
    "model and the ORIGINAL design request. Judge ONLY from the images and the request. Decide "
    "whether the model is recognizable as the requested object and whether any MAJOR requested "
    "feature is entirely missing or grossly misrepresented (e.g. a chair with no legs/casters, or "
    "all parts fused into a featureless block). Be reasonable, not perfectionist. Respond with "
    'STRICT JSON ONLY: {"recognizable": true/false, "present_features": ["..."], '
    '"missing_major_features": ["..."], "notes": "one short sentence"}.'
)

_SYSTEM_INTENT_BRIEF = (
    "You are a critical CAD design reviewer. You are shown rendered multi-view images of a 3D model, "
    "the ORIGINAL design request, and an INTENDED FORM BRIEF describing the standard form of the "
    "object (its parts, proportions, and especially orientation). Judge whether the model matches "
    "the brief in STRUCTURE, PROPORTION, PART ORIENTATION and REFINEMENT (contoured/rounded surfaces "
    "where appropriate — not crude flat slabs), and whether any MAJOR part in the brief is missing or "
    "grossly misrepresented. Judge FORM only; ignore colour/material/lighting and that the render is "
    "gray and coarse. REJECT a blocky placeholder, mis-oriented parts, or a missing major part. Put "
    "SPECIFIC, ACTIONABLE fixes in missing_major_features. Respond STRICT JSON ONLY: "
    '{"recognizable": true/false, "present_features": ["..."], "missing_major_features": ["..."], '
    '"notes": "one short sentence"}.'
)

_SYSTEM_GROUNDED = (
    "You are a senior product-design reviewer. You are shown, in order: (1) a REFERENCE image of "
    "the object the user wants, then (2) rendered multi-view images of a CAD model built to match "
    "it. Judge whether the CAD model matches the REFERENCE in STRUCTURE, PROPORTION, PART "
    "ORIENTATION, and REFINEMENT (contoured/rounded surfaces where the reference has them — not "
    "crude flat slabs). Judge FORM correspondence ONLY — ignore colour, materials, lighting, and "
    "the fact that the CAD render is gray and coarse. REJECT if the model is a blocky placeholder, "
    "if parts are mis-oriented (e.g. armrests sticking out sideways instead of forward-facing pads "
    "on vertical posts), or if major form/proportion is wrong. In missing_major_features, put "
    "SPECIFIC, ACTIONABLE fix directives (e.g. 'seat is a flat slab — give it a contoured/dished "
    "pan and round the edges', 'armrests point sideways — make them horizontal pads on vertical "
    'posts facing forward\'). Respond STRICT JSON ONLY: {"recognizable": true/false, '
    '"present_features": ["..."], "missing_major_features": ["..."], "notes": "one short sentence"}.'
)

_SYSTEM_BRIEF = (
    "You are a CAD design analyst. You are shown a REFERENCE image of an object the user wants to "
    "model in CAD. Produce a concise, structured BRIEF an engineer can build to. For EACH major "
    "part, give: NAME; the best GEOMETRY approach (a simple primitive like box/cylinder, OR a "
    "free-form surface via loft/revolve/sweep); rough PROPORTIONS / relative size; and especially "
    "its exact SPATIAL POSITION and ORIENTATION relative to the whole, and how it CONNECTS to "
    "adjacent parts. Be concrete about orientation (e.g. 'armrests: vertical posts rising from each "
    "side of the seat, with horizontal pads pointing FORWARD at elbow height'). Keep under ~250 "
    "words, plain text, one bullet per part. No preamble."
)

_SYSTEM_SPATIAL = (
    "You are a 3D spatial inspector. You are shown rendered multi-view images of a CAD model that "
    "FAILED a connectivity check (its parts should form ONE connected object but do not). Looking "
    "ONLY at the images, describe the spatial arrangement and say concretely which part(s) appear "
    "DISCONNECTED, FLOATING, or MISPLACED and roughly where they are relative to the rest. Be brief "
    "and concrete (2-4 sentences). This is the agent's only way to SEE its model — make it actionable."
)


# ---------------------------------------------------------------------------- public API
def extract_design_brief(image_path: str, prompt: str = None):
    """Turn a user REFERENCE image into a structured text BRIEF (parts, geometry approach,
    proportions, and especially ORIENTATION/connection) to guide planning. Returns the brief
    string, or None on any infra/parse error (FAIL-OPEN). Host-side; the agent reads it as text."""
    stub = os.environ.get(BRIEF_STUB_ENV)
    if stub:
        return stub
    if not image_path or not os.path.exists(image_path):
        return None
    try:
        content = [{"type": "text",
                    "text": (f"The user asked for: {prompt or '(see image)'}\n\n"
                             "Analyze the reference image and produce the build brief.")},
                   _img_block(image_path)]
        text = _vision_chat(_SYSTEM_BRIEF, content).strip()
        return text[:2000] or None
    except Exception:
        return None


_SYSTEM_BRIEF_TEXT = (
    "You are a CAD design analyst. You are given a TEXT description of an object the user wants to "
    "model in CAD (plus any clarified facts). Picture the most STANDARD, canonical real-world form "
    "of that object and produce a concise, structured BRIEF an engineer can build to. For EACH "
    "major part, give: NAME; the best GEOMETRY approach (a simple primitive like box/cylinder, OR a "
    "free-form surface via loft/revolve/sweep/twisted_loft); rough PROPORTIONS / relative size; and "
    "especially its SPATIAL POSITION and ORIENTATION relative to the whole, and how it CONNECTS to "
    "adjacent parts. If the object has repeated features (blades, legs, teeth, fins), state the "
    "COUNT and how they are arrayed. Be concrete about orientation. Keep under ~250 words, plain "
    "text, one bullet per part. No preamble."
)


def extract_design_brief_from_text(prompt, clarifications=None):
    """Imagine the object from TEXT ALONE (no reference image) and produce the SAME structured brief
    extract_design_brief produces from an image — so a no-image run gets the same upfront structural/
    orientation guidance. Returns the brief string, or None on any infra/parse error (FAIL-OPEN)."""
    stub = os.environ.get(BRIEF_STUB_ENV)
    if stub:
        return stub
    if not prompt or not str(prompt).strip():
        return None
    try:
        intent = str(prompt).strip()
        for c in (clarifications or []):
            if isinstance(c, dict):
                q = (c.get("question") or "").strip()
                a = (c.get("answer") or "").strip()
                if q or a:
                    intent += f"\n- {q} -> {a}"
        content = [{"type": "text",
                    "text": f"The user wants to design: {intent}\n\nProduce the build brief."}]
        text = (_vision_chat(_SYSTEM_BRIEF_TEXT, content) or "").strip()
        return text[:2000] or None
    except Exception:
        return None


def critique(image_paths, intent: str = None, measured_bbox=None, part_names=None) -> dict:
    """Visual judgment of the render. If a REFERENCE image is set (FORGECAD_REFERENCE_IMAGE), this
    is a strict DESIGN REVIEW grounded against it (form/orientation/refinement). Otherwise it falls
    back to the intent-only bar (recognizable + features present + size). Fail-open on infra error.
    B3: `part_names` (optional) lets the critic reference the model's actual parts so its feedback
    maps back to plan steps."""
    stub = os.environ.get(STUB_ENV)
    if stub:
        try:
            return _verdict_from_payload(json.loads(stub))
        except Exception as e:
            return _unavailable(f"bad stub: {e}")

    intent = _resolve_intent(intent)
    if not intent:
        return _unavailable("no intent provided")
    ref = _reference_image_path()

    size_line = ""
    if measured_bbox:
        try:
            dims = [round(float(x), 1) for x in measured_bbox]
            size_line = (f"\n\nMeasured bounding box of the model (mm): {dims}. If the request or "
                         "reference implies explicit dimensions or a size limit, check it and list "
                         "any violation in missing_major_features.")
        except Exception:
            pass

    # B3: orientation cues + part names so feedback is precise and maps back to plan steps.
    views_line = ("\n\nThe render shows NAMED views (front/side/top/iso) and a labeled X/Y/Z axis "
                  "triad in every panel — use them to judge ORIENTATION precisely (e.g. 'the pad "
                  "faces -Y instead of -X'). For each problem, prefer a structured item "
                  '{"part": <name or visual description>, "issue": <what is wrong>, '
                  '"fix": <concrete change>} in missing_major_features.')
    parts_line = ""
    if part_names:
        try:
            parts_line = ("\n\nThe model's named parts are: "
                          + ", ".join(str(p) for p in part_names if p)
                          + ". Reference these names in your feedback where possible.")
        except Exception:
            parts_line = ""
    extra = size_line + views_line + parts_line

    paths = image_paths if isinstance(image_paths, (list, tuple)) else [image_paths]
    try:
        if ref:
            content = [{"type": "text", "text": f"ORIGINAL DESIGN REQUEST:\n{intent}\n\n"
                                                 "(1) REFERENCE image of the intended object:"}]
            content.append(_img_block(ref))
            content.append({"type": "text", "text": "(2) Rendered views of the CAD model built to "
                                                     "match it. Return the STRICT JSON verdict." + extra})
            content += [_img_block(p) for p in paths]
            system = _SYSTEM_GROUNDED
        else:
            _brief = (os.environ.get(FORM_BRIEF_ENV) or "").strip()
            if _brief:
                content = [{"type": "text",
                            "text": (f"ORIGINAL DESIGN REQUEST:\n{intent}\n\nINTENDED FORM BRIEF:\n{_brief}"
                                     "\n\nBelow are rendered views of the produced 3D model. Return the "
                                     "STRICT JSON verdict." + extra)}]
                content += [_img_block(p) for p in paths]
                system = _SYSTEM_INTENT_BRIEF
            else:
                content = [{"type": "text",
                            "text": (f"ORIGINAL DESIGN REQUEST:\n{intent}\n\nBelow are rendered views of "
                                     "the produced 3D model. Return the STRICT JSON verdict." + extra)}]
                content += [_img_block(p) for p in paths]
                system = _SYSTEM_INTENT_ONLY
    except Exception as e:
        return _unavailable(f"could not read image: {e}")

    try:
        return _verdict_from_payload(_extract_json(_vision_chat(system, content)))
    except Exception as e:
        return _unavailable(f"{type(e).__name__}: {str(e)[:120]}")


def spatial_critique(image_paths, intent: str = None, issue: str = None, part_names=None):
    """Eyes-in-the-loop: a render-grounded description of what is disconnected/floating, so the
    (otherwise blind) agent can SEE and fix it. Returns a short string, or None on infra error.
    B3: `part_names` lets it name the model's actual parts; the render carries named views + an
    X/Y/Z axis triad for precise spatial/orientation language."""
    stub = os.environ.get(SPATIAL_STUB_ENV)
    if stub:
        return stub
    intent = _resolve_intent(intent)
    paths = image_paths if isinstance(image_paths, (list, tuple)) else [image_paths]
    parts_line = ""
    if part_names:
        try:
            parts_line = ("The model's named parts are: "
                          + ", ".join(str(p) for p in part_names if p) + ".\n")
        except Exception:
            parts_line = ""
    try:
        content = [{"type": "text",
                    "text": (f"ORIGINAL DESIGN REQUEST:\n{intent or '(unspecified)'}\n\n"
                             + parts_line
                             + (f"Automated check reports: {issue}\n\n" if issue else "")
                             + "Below are rendered NAMED views (front/side/top/iso) with a labeled "
                               "X/Y/Z axis triad. Describe the spatial layout and name what is "
                               "disconnected/floating/misplaced and roughly where (use the axes).")}]
        content += [_img_block(p) for p in paths]
        return (_vision_chat(_SYSTEM_SPATIAL, content) or "").strip()[:600] or None
    except Exception:
        return None
