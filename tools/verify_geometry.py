def verify_geometry(
    prompt: str,
    code: str,
    metrics: dict,
    render_png: str,
    prior_feedback: list | None = None,
) -> dict:
    """
    Vision-LLM judge: sends the prompt, generated CadQuery code, OCCT kernel
    metrics, and a three-view render to Gemini and returns a structured verdict.

    Args:
        prompt: Original user request.
        code: Generated CadQuery code.
        metrics: OCCT kernel measurements dict (volume, bbox, face/edge counts).
        render_png: Path to a three-view composite PNG (from render_views).
        prior_feedback: Feedback strings from previous iterations (oldest first)
            so the judge can escalate on repeated defects.

    Returns:
        {"passed": bool, "feedback": str, "render_png": str}

    Never raises. If GEMINI_API_KEY is missing/placeholder -> mock pass. On a
    judge/parse/transport failure -> {"passed": False, ...} so the outer loop
    routes to refinement instead of crashing.
    """
    import os
    import re
    import json
    import base64

    # ------------------------------------------------------------------ key
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(base_dir, ".env")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key and os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() == "GEMINI_API_KEY":
                        api_key = v.strip().strip('"').strip("'")
                        break

    # Mock fallback when no real key is configured (keyless dev / e2e).
    is_mock = not api_key or api_key == "your-key" or "YOUR" in api_key.upper()
    if is_mock:
        return {
            "passed": True,
            "feedback": "GEMINI_API_KEY not configured or placeholder. Mock verification passed.",
            "render_png": render_png,
        }

    model = os.getenv("GEMINI_JUDGE_MODEL") or os.getenv("JUDGE_MODEL") or "gemini-3.1-pro-preview"
    max_tokens = int(os.getenv("JUDGE_MAX_TOKENS", "16384"))

    validator_system = """You are the Validator Agent in the Recursive language model pwowered text to CAD generation system.
Your job is to rigorously and objectively evaluate if generated CadQuery code and its resulting geometric metrics fulfill the original user request.

You will receive:
1. The original user prompt.
2. The generated CadQuery code.
3. The exact geometric measurements from the OCCT CAD kernel (volume, bounding box, face/edge counts).
4. A rendered image of the generated part showing THREE views side by side:
   - LEFT:   Isometric view — shows overall 3D shape
   - CENTER: High-angle rear view — looks down at the top face, reveals holes,
             bores, cavities, and internal features
   - RIGHT:  Front profile view — near side-on, shows vertical profile, wall
             heights, gear spacing, slots, and layered features

IMPORTANT: The three rendered views supplement the kernel metrics — use BOTH together.
The image may not reveal every feature (hidden internal geometry, small details), but
it will help you catch major failures that metrics alone can miss:
- A shape that is fundamentally wrong (e.g., a solid block instead of a hollow shell)
- Features that appear in the code but are clearly absent in the render
- False convergence where metrics look acceptable but the part is visually incorrect
- Gross proportion errors visible at a glance

Your evaluation must be highly analytical and Socratic. Cross-reference ALL evidence:
- Does the code explicitly construct all features requested in the prompt?
- Do the kernel bounding box dimensions align with the prompt's requirements? (Note: For non-rectangular shapes like polygons, cylinders, or spheres, the bounding box will naturally be smaller than characteristic dimensions like circumscribed circle diameter. Do not flag this as an error.)
- Does the rendered image confirm that the constructed features are actually present and correct?
- Are there missing features, or extra features that were not requested?
- Is the volume physically plausible for the described shape and dimensions?
- If the prompt specifies holes, bolts, or mounting points: COUNT them in the rendered views
  and verify the number matches the prompt exactly. Also check their approximate placement
  (e.g., evenly spaced on a bolt circle, centered, at corners, etc.).

You may also receive YOUR OWN PRIOR FEEDBACK from previous iterations. This is critical:
- If you gave feedback before and the same issue persists, ESCALATE. Do not repeat the same suggestion.
- Note what was tried and failed, then recommend a fundamentally different approach.
- Example: if you said "revolve the profile" twice and the result is still flat, say
  "Previous revolve attempts failed. Try a completely different construction: extrude a
  circle and use boolean cuts instead."

Output a JSON object with EXACTLY these fields:
{
  "passed": boolean,
  "feedback": "Direct, analytical feedback detailing exact discrepancies. If passed, write 'All constraints met.' If failed, state exactly what is wrong — referencing what you see in the image AND the metrics — and suggest a DIFFERENT approach if prior feedback was not addressed."
}
Output ONLY valid JSON, no other text."""

    # ------------------------------------------------------------- text block
    text_content = (
        f"ORIGINAL PROMPT:\n{prompt}\n\n"
        f"GENERATED CODE:\n```python\n{code}\n```\n\n"
        f"KERNEL METRICS:\n{json.dumps(metrics, indent=2)}\n\n"
    )
    if prior_feedback:
        text_content += "YOUR PRIOR FEEDBACK (from previous iterations, oldest first):\n"
        for i, fb in enumerate(prior_feedback):
            text_content += f"  Iteration {i}: {fb}\n"
        text_content += "\nIf the same issues persist, escalate — recommend a fundamentally different approach.\n\n"
    text_content += "Evaluate and return JSON."

    # ---------------------------------------------------- robust JSON extract
    def _repair_json_strings(s: str) -> str:
        result = []
        in_string = False
        escape_next = False
        for ch in s:
            if escape_next:
                result.append(ch)
                escape_next = False
            elif ch == "\\" and in_string:
                result.append(ch)
                escape_next = True
            elif ch == '"':
                result.append(ch)
                in_string = not in_string
            elif in_string and ch == "\n":
                result.append("\\n")
            elif in_string and ch == "\r":
                result.append("\\r")
            elif in_string and ch == "\t":
                result.append("\\t")
            elif in_string and ord(ch) < 0x20:
                result.append(f"\\u{ord(ch):04x}")
            else:
                result.append(ch)
        return "".join(result)

    def _extract_json(response: str) -> dict:
        text = response.strip()
        if "```json" in text:
            start = text.index("```json") + len("```json")
            end = text.find("```", start)
            if end != -1:
                text = text[start:end].strip()
        elif text.startswith("```"):
            start = text.index("\n") + 1 if "\n" in text else 3
            end = text.rfind("```")
            if end > start:
                text = text[start:end].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            candidate = text[brace_start:brace_end + 1]
            for attempt in (candidate, _repair_json_strings(candidate)):
                try:
                    return json.loads(attempt)
                except json.JSONDecodeError:
                    pass
            try:
                cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", _repair_json_strings(candidate))
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass
        preview = response[:500].replace('"', "'")
        return {
            "passed": False,
            "feedback": (
                f"[verifier-parse-error] Could not extract JSON verdict from judge "
                f"response (length={len(response)}). Treating as failed for safety. "
                f"Preview: {preview}"
            ),
        }

    # ---------------------------------------------------------- call the judge
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        parts = [types.Part.from_text(text=text_content)]
        if render_png and os.path.exists(render_png):
            with open(render_png, "rb") as f:
                parts.append(types.Part.from_bytes(data=f.read(), mime_type="image/png"))

        response = client.models.generate_content(
            model=model,
            contents=parts,  # type: ignore
            config=types.GenerateContentConfig(
                system_instruction=validator_system,
                max_output_tokens=max_tokens,
            ),
        )

        if not response.candidates:
            block_reason = getattr(response.prompt_feedback, "block_reason", "unknown")
            return {
                "passed": False,
                "feedback": f"[verifier-error] Gemini returned no candidates (model={model}, block={block_reason}).",
                "render_png": render_png,
            }

        verdict = _extract_json(response.text or "")
        return {
            "passed": bool(verdict.get("passed", False)),
            "feedback": str(verdict.get("feedback", "")),
            "render_png": render_png,
        }

    except Exception as e:
        return {
            "passed": False,
            "feedback": f"[verifier-error] Gemini judge call failed: {str(e)}. Treating as failed.",
            "render_png": render_png,
        }
