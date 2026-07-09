"""Generic VLM judge for rendered geometry."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

JUDGE_INSTRUCTION = """You are a precise vision-language verifier for generated CAD geometry.

WHAT YOU RECEIVE
1. The user's request (natural language).
2. A required-feature checklist — the concrete, visible features the object MUST
   have. May be empty (then judge against the request alone).
3. Deterministic geometry metrics measured from the ACTUAL solid (bounding box in
   mm, volume, component count, watertight, PLUS structural signals below). These
   are ground truth — trust them over your eyeballing of the render, especially
   where the projection is ambiguous.
   - solid_fraction = volume / bounding-box-volume. Near 1.0 means a SOLID block
     filling its envelope; a low value means hollow/open. If the request wants a
     hollow part (duct, pipe, shell, cup, tube, adapter with a bore) but
     solid_fraction is ≈1.0, it is a SOLID plug — fail (missing_feature), even
     though every exterior view looks identical to the correct hollow part.
   - section_fill = filled-area fraction at 5 cross-sections (base→top) along each
     of X/Y/Z. This is viewpoint-INDEPENDENT: a drop at a slice means a real gap /
     hollow / missing chunk there, and a flat 1.0 run means solid there. Use it to
     COUNT and LOCATE structure (missing cubelets, through-holes, internal cavities,
     taper) instead of inferring from a foreshortened render. Do NOT count discrete
     features by eye off the isometric view — reconcile against section_fill.
4. A rendered 3-view PNG (isometric, high rear, low front) of the geometry.
5. (Optional) the specific fix the last replan attempted.

HOW TO JUDGE — in this order
1. GROSS SHAPE: does the render read as the requested object type at all? If it
   is clearly the wrong kind of thing, that alone is a fail (failure_type
   "wrong_shape").
2. PER FEATURE: for EACH required-feature checklist item, decide present / missing
   / wrong. A feature that is technically in the geometry but too small, thin, or
   shallow to actually read counts as MISSING or WRONG, not present — use the
   metrics to sanity-check scale (e.g. a "tall side frame" that is only a few
   percent of the bounding-box height is effectively missing).
3. PROPORTION & PLACEMENT: are present features sized and positioned sensibly
   relative to each other and to the whole (bounding box)?

FEEDBACK RULES (critical — this drives the fix)
- Be SPECIFIC and QUANTITATIVE. Never write only "missing X". Say WHAT is wrong and
  HOW to fix it in plan terms — concrete dimensions / positions / counts. Example:
  "side frames read as thin rails ~8% of base height; make them vertical walls
  ~40-60% of the 240mm depth and move them to the two long edges".
- Reference the metrics when judging scale (bbox dimensions, component count).
- If num_components > 1 for something meant to be one connected part, call that out
  (features are only touching, not overlapping/fused).
- If the last replan's fix is provided, state explicitly whether it landed.

Return ONLY JSON:
{
  "passed": true | false,
  "object_ok": true | false,
  "failure_type": "none" | "wrong_shape" | "missing_feature" | "extra_feature"
    | "wrong_count" | "wrong_placement" | "wrong_proportion" | "unclear",
  "feature_findings": [
    {"feature": "<checklist item or observed feature>",
     "status": "present" | "missing" | "wrong",
     "note": "specific, quantitative critique + concrete fix in dimensions/position"}
  ],
  "feedback": "1-3 sentence actionable summary for the replanner; 'All constraints met.' if passed."
}
"""


def judge_geometry_render(
    prompt: str,
    render_png: str,
    last_replan_feedback: str | None = None,
    metrics: dict[str, Any] | None = None,
    feature_checklist: str = "",
    feedback_history: list[str] | None = None,
) -> dict[str, Any]:
    """Judge whether a render matches the user's requested geometry.

    Grounded by three extra inputs beyond the render:
      - feature_checklist: the required-feature contract from intake (Task 2),
        so the judge checks each named feature, not a vibe.
      - metrics: deterministic geometry numbers (bbox/volume/components), so the
        judge reasons about SCALE from ground truth, not eyeballing pixels.
      - feedback_history: EVERY prior attempt's failure detail (oldest->newest),
        so the judge can spot a defect that has survived multiple replans and
        stop rubber-stamping the same unfixed part as "present".

    last_replan_feedback: the failure detail the replanner most recently acted
    on (None on a first attempt) — lets the judge check whether THAT fix landed.
    """
    if not Path(render_png).exists():
        return _error(f"Render PNG not found: {render_png}", render_png)

    try:
        response_text = _call_vlm(
            prompt,
            render_png,
            last_replan_feedback,
            metrics,
            feature_checklist,
            feedback_history,
        )
        return _format_verdict(_read_json(response_text), render_png)
    except Exception as exc:
        return _error(f"VLM judge failed: {exc}", render_png)


def _call_vlm(
    prompt: str,
    render_png: str,
    last_replan_feedback: str | None,
    metrics: dict[str, Any] | None = None,
    feature_checklist: str = "",
    feedback_history: list[str] | None = None,
) -> str:
    """Call the configured vision model with request + checklist + metrics + history + image."""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")

    with open(render_png, "rb") as image_file:
        image_bytes = image_file.read()

    text = f"USER REQUEST:\n{prompt}"
    if feature_checklist.strip():
        text += f"\n\n{feature_checklist.strip()}"
    if metrics:
        text += f"\n\nMEASURED GEOMETRY METRICS (ground truth):\n{_format_metrics(metrics)}"
    # Full replan history (excluding the most recent, shown separately below) so
    # the judge sees the whole failure trail, not just the last note.
    prior = [f for f in (feedback_history or []) if f][:-1] if last_replan_feedback else [
        f for f in (feedback_history or []) if f
    ]
    if prior:
        trail = "\n".join(f"  {i}. {f}" for i, f in enumerate(prior, 1))
        text += (
            f"\n\nPRIOR ATTEMPTS ALREADY FAILED FOR (oldest first):\n{trail}\n"
            f"If any of these defects is STILL visible, do NOT pass — a repeated "
            f"unfixed failure is a fail, not 'present'."
        )
    if last_replan_feedback:
        text += (
            f"\n\nTHIS ATTEMPT WAS REPLANNED TO FIX:\n{last_replan_feedback}\n"
            f"Check specifically whether that was addressed, in addition to the "
            f"original request and checklist above."
        )

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=os.environ.get("VLM_JUDGE_MODEL", "gemini-3.1-pro-preview"),
        contents=[
            types.Part.from_text(text=text),
            types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
        ],
        config=types.GenerateContentConfig(
            system_instruction=JUDGE_INSTRUCTION,
            response_mime_type="application/json",
            # gemini-3.1-pro-preview is a THINKING model — with no budget set,
            # internal reasoning tokens can exhaust the default output cap before
            # the actual JSON gets written, truncating it mid-object ("unterminated
            # JSON object"). thinking_budget=0 and ThinkingLevel.MINIMAL are BOTH
            # rejected by this model (400 INVALID_ARGUMENT — "only works in
            # thinking mode" / "MINIMAL is not supported"); LOW is the lowest
            # level it actually accepts (probed live). Pair with a generous
            # max_output_tokens so thinking + the final JSON both fit.
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
            max_output_tokens=4096,
        ),
    )
    return response.text or ""


def _read_json(text: str) -> dict[str, Any]:
    """Read a JSON object from the VLM response."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        candidate = _first_json_object(cleaned)
        return json.loads(candidate)


def _first_json_object(text: str) -> str:
    """Return the first balanced JSON object in text."""
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found")

    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text[start:], start=start):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    raise ValueError("unterminated JSON object")


def _format_metrics(metrics: dict[str, Any]) -> str:
    """Render the deterministic geometry metrics as a compact ground-truth block."""
    bb = metrics.get("bounding_box") or metrics.get("bbox") or {}
    parts: list[str] = []
    if bb:
        dx = round(float(bb.get("xmax", 0)) - float(bb.get("xmin", 0)), 1)
        dy = round(float(bb.get("ymax", 0)) - float(bb.get("ymin", 0)), 1)
        dz = round(float(bb.get("zmax", 0)) - float(bb.get("zmin", 0)), 1)
        parts.append(f"bbox_size_mm = {dx} x {dy} x {dz}  (X x Y x Z)")
    if metrics.get("volume_mm3") is not None:
        parts.append(f"volume_mm3 = {round(float(metrics['volume_mm3']), 1)}")
    if metrics.get("num_components") is not None:
        parts.append(f"num_components = {metrics['num_components']}")
    if metrics.get("is_watertight") is not None:
        parts.append(f"watertight = {metrics['is_watertight']}")
    if metrics.get("solid_fraction") is not None:
        sf = float(metrics["solid_fraction"])
        hint = "≈solid block" if sf >= 0.92 else ("hollow/open" if sf <= 0.6 else "partially hollow")
        parts.append(f"solid_fraction = {round(sf, 3)}  (volume/bbox; {hint})")
    prof = metrics.get("section_profile")
    if isinstance(prof, dict) and any(prof.values()):
        # filled-area fraction at 5 cross-sections (base→top) along each axis;
        # a drop = a gap / hollow / missing chunk at that slice, INDEPENDENT of
        # viewing angle. Use this to count/locate structure instead of eyeballing.
        rows = []
        for ax in ("X", "Y", "Z"):
            vals = prof.get(ax)
            if vals:
                rows.append(f"    {ax}: {vals}")
        if rows:
            parts.append("section_fill (5 slices base→top, filled-area / cross-section):\n" + "\n".join(rows))
    return "\n".join(f"- {p}" for p in parts) or "- (no metrics available)"


def _format_verdict(verdict: dict[str, Any], render_png: str) -> dict[str, Any]:
    """Return the stable payload used by the geometry loop.

    Preserves the historical keys (passed / failure_type / feedback /
    failure_stage / verifier_ran / render_png) and ADDS the grounded extras
    (object_ok, feature_findings) that the enriched replan feedback (Task 4)
    forwards to the replanner. Older callers that ignore the new keys are
    unaffected.
    """
    passed = bool(verdict.get("passed"))
    failure_type = str(verdict.get("failure_type") or "wrong_shape")
    if passed:
        failure_type = "none"

    feedback = str(verdict.get("feedback") or "").strip()
    if passed:
        feedback = feedback or "All constraints met."
    elif not feedback.startswith("[visual_failure:"):
        feedback = (
            f"[visual_failure:{failure_type}] "
            f"{feedback or 'Rendered geometry does not match the request.'}"
        )

    findings = verdict.get("feature_findings")
    findings = findings if isinstance(findings, list) else []

    return {
        "passed": passed,
        "object_ok": bool(verdict.get("object_ok", passed)),
        "failure_type": failure_type,
        "feature_findings": findings,
        "feedback": feedback,
        "render_png": render_png,
        "verifier_ran": True,
        "failure_stage": "" if passed else "visual_mismatch",
    }


def _error(message: str, render_png: str) -> dict[str, Any]:
    """Return a fail-closed verifier error."""
    return {
        "passed": False,
        "failure_type": "verifier_error",
        "feedback": f"[verifier-error] {message}",
        "render_png": render_png,
        "verifier_ran": False,
        "failure_stage": "verifier_error",
    }
