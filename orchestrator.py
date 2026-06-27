"""
orchestrator.py — ForgeCAD v4 entrypoint (stateful, single-loop).

v4 philosophy
-------------
The RLM is the reasoner, not a form-filler. It drafts a GeometryPlan AND drives
its OWN build -> verify loop in one stateful REPL session, against the host
geometry kernel (real CadQuery/OCP + MeshLib) exposed over MCP. Heavy solids
live host-side; only ids + JSON reports cross back into the agent's context.

What the host still owns (NON-NEGOTIABLE, not bandages):
  - the deterministic kernel (primitives from fixed templates, mate resolution),
  - the FIXED verification battery (the generator never grades itself),
  - the data-contract schema (GeometryPlan / validate_plan).

What the host NO LONGER does (the bandages, removed in v4):
  - stateless re-run repair loops (build / validate / verify repair),
  - normalize_aliases / confusable auto-remap (the agent fixes invented names
    itself from validate_plan's error + valid list),
  - bbox auto-sync (the agent reconciles declared vs measured dims in-loop),
  - the "do not call llm_query" prohibition (scoped recursion is allowed).

Stopping: there is NO host-side retry count. Termination is governed by fast-rlm's
native budgets (max_calls_per_subagent / max_global_calls / money+token caps) plus
the in-agent termination contract documented in skills/core.md.
"""

import os
import sys
import json
import secrets
import tempfile
import importlib.util
from pathlib import Path

import yaml
from dotenv import load_dotenv

import fast_rlm
from tools import get_tools
from trace_view import render_trace
from cad_kernel import kernel, verify as verify_mod, render as render_mod, attestation
import plan_store

load_dotenv()

# ==========================================
# 1. Credentials & Endpoint Setup
# ==========================================
if not os.environ.get("RLM_MODEL_API_KEY"):
    raise RuntimeError("RLM_MODEL_API_KEY is missing. Please set it in your .env file.")

api_key = os.environ.get("RLM_MODEL_API_KEY", "")
DEFAULT_CONFIG_PATH = Path(__file__).parent / "run.yaml"

_cfg_preview = yaml.safe_load(open(DEFAULT_CONFIG_PATH)) or {} if DEFAULT_CONFIG_PATH.exists() else {}
_model_base_url = os.environ.get("RLM_MODEL_BASE_URL") or _cfg_preview.get("model_base_url")
if not _model_base_url:
    _GEMINI_KEY_PREFIXES = ("AIzaSy", "AQ.")
    if any(api_key.startswith(p) for p in _GEMINI_KEY_PREFIXES):
        _model_base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
if _model_base_url:
    os.environ["RLM_MODEL_BASE_URL"] = _model_base_url
    print(f"[INFO] Using model base URL: {_model_base_url}")


CONFIG_KEYS = {
    "primary_agent", "sub_agent", "max_depth", "max_calls_per_subagent",
    "truncate_len", "max_money_spent", "max_completion_tokens",
    "max_prompt_tokens", "max_global_calls", "api_max_retries", "api_timeout_ms",
    "enable_tools", "enable_structured_io", "enable_compression_guard",
    "compression_min_chars", "compression_ratio",
}
LLM_KEYS = {"temperature", "top_p", "seed", "top_k",
            "presence_penalty", "frequency_penalty"}


def load_run_config(path=DEFAULT_CONFIG_PATH):
    cfg = yaml.safe_load(open(path)) or {}
    config = {k: v for k, v in cfg.items() if k in CONFIG_KEYS and v is not None}
    llm_kwargs = {k: v for k, v in cfg.items() if k in LLM_KEYS and v is not None}
    flags = {k: v for k, v in cfg.items()
             if k not in CONFIG_KEYS and k not in LLM_KEYS and v is not None}
    return config, llm_kwargs, flags


def load_pydantic_schema(path: Path):
    """Dynamically load the root Pydantic model from a Python file path."""
    module_name = path.stem
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from spec at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    from pydantic import BaseModel
    models = {}
    for attr_name in dir(module):
        if attr_name.startswith("_"):
            continue
        attr = getattr(module, attr_name)
        if isinstance(attr, type) and issubclass(attr, BaseModel) and attr is not BaseModel:
            models[attr_name] = attr
    if not models:
        raise ValueError(f"No Pydantic BaseModel subclass found in {path}")

    normalized_module = module_name.replace("_", "").lower()
    for name, model in models.items():
        if name.lower() == normalized_module:
            return model
    referenced = set()
    for name, model in models.items():
        for _fn, field in model.model_fields.items():
            ann = field.annotation
            if ann:
                ann_str = str(ann)
                for other in models:
                    if other != name and other in ann_str:
                        referenced.add(other)
    roots = [n for n in models if n not in referenced]
    if roots:
        return models[roots[0]]
    return models[sorted(models.keys())[0]]


def generate_primitives_summary():
    """Compact primitive reference (names + param keys + the confusable-name hints).
    Kept short on purpose; the agent calls get_primitives_library() for full schemas.
    The confusable hints are a PROMPT HINT only (no host auto-remap) — the agent is
    expected to read them and never invent a name."""
    primitives_path = Path(__file__).parent / "schemas" / "primitives.json"
    if not primitives_path.exists():
        return ""
    with open(primitives_path, "r", encoding="utf-8") as f:
        primitives = json.load(f)

    confusables = {
        "rounded_box": "filleted_box", "tube": "hollow_cylinder",
        "plate": "box", "polygon": "prism", "polygon_extrusion": "prism",
        "beveled_box": "chamfered_box", "donut": "torus", "flat_ring": "ring",
    }
    real_to_aliases = {}
    for alias, real in confusables.items():
        real_to_aliases.setdefault(real, []).append(alias)

    lines = [
        "\n### Geometric vocabulary (EXACT keys — use nothing else)",
        "Call get_primitives_library() for full parameter schemas and defaults. Build like a real "
        "manufactured part: choose the operation that matches the FORM, and ROUND / CONTOUR / "
        "HOLLOW instead of leaving sharp blocky boxes. Compose certified BUILDER primitives (below) "
        "with the MODIFIER verbs (fillet/chamfer/shell) and the contour builders "
        "(lofted_box / revolved_profile / swept_circle). HYBRID: use primitives where EXACT "
        "dimensions/interfaces matter (holes, mating faces, structural sections); use 'custom' "
        "(KB-guided loft/revolve/sweep) for free-form aesthetic surfaces. If a REFERENCE FORM BRIEF "
        "is in your task, build to MATCH its structure, proportions, and ORIENTATION.",
        "",
        "  MODIFIER verbs (refine the running solid built so far — supply numbers only):",
        "    **fillet** [radius, edges] — round edges (edges: all|vertical|top|bottom)",
        "    **chamfer** [distance, edges] — bevel edges",
        "    **shell** [thickness, face] — hollow to a wall, opening one face (top|bottom|left|right|front|back)",
        "  CONTOUR builders (curved/organic forms — supply numbers/points only, NO custom code):",
        "    **lofted_box** — a slab/seat-pan/tapered form lofted between a bottom and top rectangle",
        "    **lofted_sections** — GENERAL loft through arbitrary cross-sections [[z,x1,y1,...],...]",
        "      (dished seat pan, bottle body, wing/duct section, organic taper — not just box->box)",
        "    **revolved_profile** — a turned form (vase/knob/bottle) from a [[r,z],...] profile (+ optional end_fillet)",
        "    **swept_circle** — a round tube/handle/rod swept along a [[x,y,z],...] path",
        "    **swept_profile** — GENERAL sweep of an arbitrary [x,y] cross-section along a [[x,y,z],...] path",
        "      (rectangular/elliptical rail, contoured handle). Prefer these over 'custom' for curves.",
        "",
        "  Builder primitives:",
    ]
    for name, data in sorted(primitives.items()):
        desc = data.get("description", "").split(".")[0]
        params = ", ".join(data.get("parameters", {}).keys())
        base = f"  **{name}** [{params}] — {desc}"
        aliases = real_to_aliases.get(name, [])
        if aliases:
            base += "  ← use this, NOT " + ", ".join(f'"{a}"' for a in aliases)
        lines.append(base)
    lines.append("")
    lines.append("  These names do NOT exist (validate_plan will reject them):")
    for alias, real in sorted(confusables.items()):
        lines.append(f'    "{alias}" -> use **{real}**')
    return "\n".join(lines)


CLARIFIER_ROLE = (
    "You help ANY user — technical or not — pin down only the few NON-NEGOTIABLE facts needed to "
    "model their object, where a wrong guess would force a redesign. Ask AT MOST 3 short questions, "
    "ONLY about: (1) overall SIZE or the space it must fit in; (2) the COUNT of the main repeated "
    "feature if it matters (e.g. number of blades/legs/shelves); (3) any critical ORIENTATION or "
    "how/where it MOUNTS or connects; (4) MATERIAL only if it changes the shape. Skip anything with "
    "a safe standard default. RULES for each question: use PLAIN, everyday language (NO jargon like "
    "'IP rating', 'load path', 'bolt PCD' — if such a concept matters, explain it in simple words); "
    "give 2-4 concrete EXAMPLE answers in parentheses so a non-expert can just pick one; and always "
    "end with an escape like \"(or say 'use standard defaults' / 'not sure')\". Example size "
    "question: \"About how big should it be? (fits in your hand ~10 cm / desktop ~30-50 cm / "
    "furniture-sized ~1 m, or give a number in mm; or say 'use standard defaults')\". Output STRICT "
    'JSON: {"questions": ["...", "..."]} with at most 3 questions, or {"questions": []} if the '
    "request already specifies everything important. Ask nothing else."
)


def generate_clarification_questions(user_prompt, config, llm_kwargs, flags):
    """Generate up to 3 critical clarifying questions for a request (the question-generation half
    of clarification, with no asking). Reused by the CLI clarifier AND the test UI. Fail-safe -> []."""
    if not flags.get("clarify", True):
        return []
    questions = []
    try:
        q_schema = {"type": "object",
                    "properties": {"questions": {"type": "array", "items": {"type": "string"}}},
                    "required": ["questions"]}
        clar_cfg = dict(config or {})
        clar_cfg["max_depth"] = 0
        res = fast_rlm.run(
            query={"role_instructions": CLARIFIER_ROLE,
                   "task_instructions": f"Design request: '{user_prompt}'."},
            prefix="clarifier", config=clar_cfg, llm_kwargs=llm_kwargs or None,
            output_schema=q_schema, verbose=False)
        questions = ((res.get("results") or {}).get("questions") or [])[:3]
    except Exception as e:
        print(f"[clarify] question pass skipped ({e}); planning will proceed without it.")
        questions = []

    import re as _re
    if not questions and not _re.search(r"\d", user_prompt or ""):
        questions = ["This request doesn't specify key parameters. What should I design to — "
                     "overall size (mm), load/weight capacity, material, and any required "
                     "features? (reply with specifics, or 'use sensible defaults')"]
        print("[clarify] prompt is under-specified — asking one consolidated question.")
    return [q.strip() for q in questions if (q or "").strip()]


# P4: normalize a clarifier answer so downstream intent/critique is DETERMINISTIC regardless of how
# a user phrases "I don't care". Blank -> None (drop, agent uses defaults); a vague answer -> a
# canonical default string.
import re as _re_clar
_VAGUE_ANSWER_RE = _re_clar.compile(
    r"^(?:idk|i\s*don'?t\s*know|not\s*sure|dunno|no\s*idea|any(?:thing)?|whatever|"
    r"standard|sensible|defaults?|use\s+(?:standard|sensible|your)\s+\w+|you\s+(?:decide|choose)|n/?a|-)$",
    _re_clar.IGNORECASE)


def _normalize_clarification_answer(ans):
    """Blank -> None (drop). A vague answer ('idk', 'standard', 'use defaults', 'not sure', ...) ->
    'use sensible standard defaults'. Anything concrete -> unchanged."""
    a = (ans or "").strip()
    if not a:
        return None
    if _VAGUE_ANSWER_RE.match(a):
        return "use sensible standard defaults"
    return a


# P5: extract an EXPLICIT user-stated size into a conservative MAX-ENVELOPE cap (mm).
_DIM_RE = _re_clar.compile(
    r"(\d+(?:\.\d+)?)\s*(mm|millimet(?:er|re)s?|cm|centimet(?:er|re)s?|m|met(?:er|re)s?|in|inch|inches|\")\b",
    _re_clar.IGNORECASE)


def _extract_size_constraint(user_prompt, established_qa):
    """Find EXPLICIT numeric size statements (number + length unit) in the prompt + clarifier answers
    and turn them into a conservative MAX-ENVELOPE cap (mm). Returns {'max_extent_mm', 'source'} or
    None. CONSERVATIVE + FAIL-OPEN: fires ONLY on a clear number+unit; caps at 1.15x the largest
    stated dimension (a gross-oversize guard, not precision); min-size/proportion stay advisory."""
    try:
        text = str(user_prompt or "")
        for c in (established_qa or []):
            if isinstance(c, dict):
                text += " " + str(c.get("answer") or "")
        best_mm = 0.0
        best_src = None
        for m in _DIM_RE.finditer(text):
            val = float(m.group(1))
            unit = m.group(2).lower()
            if unit.startswith("milli") or unit == "mm":
                f = 1.0
            elif unit.startswith("centi") or unit == "cm":
                f = 10.0
            elif unit in ('"',) or unit.startswith("inch") or unit == "in":
                f = 25.4
            elif unit == "m" or unit.startswith("met"):
                f = 1000.0
            else:
                f = 1.0
            mm = val * f
            if mm > best_mm:
                best_mm, best_src = mm, m.group(0)
        if best_mm <= 0:
            return None
        return {"max_extent_mm": round(best_mm * 1.15, 3), "source": best_src}
    except Exception:
        return None


def gather_clarifications(user_prompt, config, llm_kwargs, flags):
    """Dedicated pre-planning pass: surface up to 3 critical questions, ASK the user (terminal/GUI),
    return real Q&A. Single-purpose model call (depth 0). Fail-safe: any problem -> []."""
    if not flags.get("clarify", True):
        return []
    try:
        from tools.clarify_io import ask_user_impl
    except Exception as e:
        print(f"[clarify] disabled (io import failed: {e})")
        return []
    questions = generate_clarification_questions(user_prompt, config, llm_kwargs, flags)

    qa = []
    for q in questions:
        q = (q or "").strip()
        if not q:
            continue
        print(f"[clarify] asking: {q}")
        ans = ask_user_impl(q)
        if ans and not ans.startswith("[UNANSWERED"):
            norm = _normalize_clarification_answer(ans)
            if norm:
                qa.append({"question": q, "answer": norm})
    if qa:
        print(f"[clarify] gathered {len(qa)} answer(s) from the user.")
    return qa


def _resolve_mcp_python():
    """Pick an interpreter that can run the host MCP servers. Both servers need `mcp`;
    geometry_server additionally needs cadquery + meshlib. The orchestrator is expected
    to run inside the project venv that already has the full stack, so sys.executable is
    correct in the normal case. We validate it imports `mcp` and fall back to PATH."""
    import shutil as _shutil
    import subprocess as _sp
    candidates = [sys.executable]
    for name in ("python3", "python"):
        found = _shutil.which(name)
        if found and found not in candidates:
            candidates.append(found)
    for cand in candidates:
        try:
            r = _sp.run([cand, "-c", "import mcp"], capture_output=True)
            if r.returncode == 0:
                return cand
        except Exception:
            continue
    return sys.executable


def _declared_bbox(plan_dict):
    ov = plan_dict.get("overall_dimensions") or {}
    if not ov:
        return None
    return [ov.get("width", 0), ov.get("length", 0), ov.get("height", 0)]


def main():
    """CLI entry: clarify in the terminal, then run the pipeline."""
    config, llm_kwargs, flags = load_run_config()
    print("\n--- ForgeCAD: Stateful Geometry Agent ---")
    user_prompt = input("Enter your CAD design request (or press enter for default: "
                        "'Design a mounting bracket for a camera enclosure to be mounted "
                        "outdoors on a brick wall'): ")
    if not user_prompt.strip():
        user_prompt = ("Design a mounting bracket for a camera enclosure to be mounted "
                       "outdoors on a brick wall")
    established_qa = gather_clarifications(user_prompt, config, llm_kwargs, flags)
    ref = os.environ.get("FORGECAD_REFERENCE_IMAGE")  # optional, e.g. set by a wrapper
    try:
        result = run_pipeline(user_prompt, established_qa, reference_image_path=ref)
    except PipelineError:
        sys.exit(1)
    sys.exit(0 if result.get("ok") else 1)


def run_pipeline(user_prompt, established_qa, reference_image_path=None):
    """Run the full stateful pipeline for a prompt + already-gathered clarifier answers (+ an
    OPTIONAL user reference image). Used by the CLI and the test UI. Returns a result dict on
    success; raises PipelineError on an honest failure (the caller decides exit/display).

    If a reference image is given, we extract a text FORM BRIEF from it (host-side vision) and feed
    it to the planner, and pass the image path to the kernel server so the design-review critic can
    judge the render AGAINST the reference. With no reference, behaviour is exactly as before."""
    asked_file = Path(__file__).parent / ".asked_clarifications.json"
    if asked_file.exists():
        try:
            asked_file.unlink()
        except Exception:
            pass

    config, llm_kwargs, flags = load_run_config()

    established_block = ""
    if established_qa:
        facts = chr(10).join(f"  - {c['question']} -> {c['answer']}" for c in established_qa)
        established_block = ("These requirements were ALREADY clarified with the user; "
                             "treat them as given facts:" + chr(10) + facts)

    # Reference image -> text form brief (host-side; the agent reads it as text). Fail-open.
    reference_block = ""
    _text_form_brief = None          # set ONLY in the NO-IMAGE case (used to strengthen the bar, P2)
    if reference_image_path and os.path.exists(reference_image_path):
        try:
            from cad_kernel import fidelity as _fid
            brief = _fid.extract_design_brief(reference_image_path, user_prompt)
            if brief:
                reference_block = (
                    "REFERENCE FORM BRIEF — a reference image of the target was provided. BUILD TO "
                    "MATCH its structure, proportions, and especially PART ORIENTATION. You will be "
                    "design-reviewed against this reference: a crude/blocky or mis-oriented result "
                    "will be REJECTED. Use the contour builders (lofted_box/revolved_profile/swept_circle) "
                    "and fillet/chamfer/shell to match its refinement:" + chr(10) + brief)
                print("[reference] design brief extracted from the reference image.")
            else:
                print("[reference] no brief produced (vision unavailable) — proceeding without it.")
        except Exception as e:
            print(f"[reference] brief extraction skipped ({e}); proceeding without it.")
    else:
        # NO reference image: reason a FORM BRIEF from the text description (multimodal model in
        # text mode), so a no-image run gets the SAME upfront structural/orientation guidance as a
        # with-image run. Fail-open: any error -> no brief -> behaviour exactly as before.
        try:
            from cad_kernel import fidelity as _fid
            _text_form_brief = _fid.extract_design_brief_from_text(user_prompt, established_qa)
            if _text_form_brief:
                reference_block = (
                    "FORM BRIEF (reasoned from your description — no reference image was given). BUILD "
                    "TO MATCH this structure, proportions, and especially PART ORIENTATION; the design "
                    "critic will check the result looks like this. Use the contour builders "
                    "(lofted_box / revolved_profile / swept_circle / swept_profile / lofted_sections / "
                    "twisted_loft) and fillet/chamfer/shell so it is refined, not blocky:" + chr(10) + _text_form_brief)
                print("[brief] form brief reasoned from the text description.")
        except Exception as e:
            print(f"[brief] text brief skipped ({e}); proceeding without it.")

    # ---- Opt-in EDIT MODE (inter-run statefulness): FORGECAD_EDIT=<id|label|latest> loads a
    #      previously accepted plan; the agent modifies it minimally instead of starting over.
    edit_block = ""
    edit_ref = os.environ.get("FORGECAD_EDIT")
    if edit_ref:
        try:
            prior = plan_store.load_plan(edit_ref)
            edit_block = ("EDIT MODE — start from this previously ACCEPTED, verified plan and change "
                          "ONLY what the user now asks for, keeping everything else identical; then "
                          "re-build and re-verify:" + chr(10) + json.dumps(prior, indent=2))
            print(f"[edit] loaded prior plan '{edit_ref}' ({len(prior.get('primitives_sequence', []))} steps)")
        except Exception as e:
            print(f"[edit] could not load '{edit_ref}' ({e}); proceeding as a fresh design.")

    # ---- The stateful task: draft -> validate -> build+verify -> reason -> repeat -> FINAL.
    task_lines = [
        "START HERE (read this once, then BUILD — do not spend many steps re-reading):",
        "  1. Parse helpers (define ONCE; mcp_call returns a STRING/dict — parse it):",
        "       import json",
        "       async def call(s,t,**k): r = await mcp_call(s,t,**k); return json.loads(r) if isinstance(r,str) else r",
        "       async def build_verify(P): return await call('geometry_kernel','build_verify_render', plan=P)",
        "       async def validate(P):     return await call('host_tools','validate_plan', plan=P)",
        "  2. Draft a plan P from the CERTIFIED PRIMITIVES below and call await build_verify(P) EARLY",
        "     (within your first few steps). Iterate on the returned report — that is the whole loop.",
        "  3. MULTI-PART OBJECTS (chair, gearbox, lamp, ...): use assembly_kind='assembly' and make each",
        "     rigid piece its OWN part (operation 'new') connected by `attach` so parts TOUCH. This needs",
        "     NO boolean fuse — the kernel snaps attached parts into contact. Do NOT `join`/fuse many",
        "     pieces (fusing curved/swept geometry is fragile); reserve join/cut for a single monolith.",
        "  4. Primitive schemas and the CadQuery KB are LAZY lookups — fetch a specific one only when a",
        "     step needs it; do not dump them all up front.",
        "",
        f"The user wants to design: '{user_prompt}'.",
        "",
        established_block,
        reference_block,
        edit_block,
        "",
        "You will produce ONE GeometryPlan AND prove it is geometrically sound by building",
        "and verifying it yourself, in this REPL, before you FINAL. You keep full state across",
        "steps (variables persist) — never restart your reasoning; iterate on it.",
        "",
        "TOOL/CODE BOUNDARY (read this first):",
        "  - You author the plan as a Python DICT. You do NOT run CAD here. CadQuery/OCP is NOT",
        "    importable in this REPL — `import cadquery` will FAIL. The host kernel is the ONLY thing",
        "    that executes geometry, via build_verify_render. A 'custom' step's code_sketch is TEXT you",
        "    put inside the plan dict (a string); the host runs it, not you. Never `import cadquery`.",
        "",
        "TOOLS (call mcp_call with await; native tools without await):",
        "  RESULT PARSING (critical): await mcp_call(...) returns a JSON STRING, not a ready dict.",
        "  Define helpers ONCE and reuse them, so you can actually read verdict/token:",
        "      import json",
        "      async def call(s,t,**k):",
        "          r = await mcp_call(s,t,**k)",
        "          return json.loads(r) if isinstance(r, str) else r",
        "      async def build_verify(P): return await call('geometry_kernel','build_verify_render', plan=P)",
        "      async def validate(P):     return await call('host_tools','validate_plan', plan=P)",
        "  NEVER do v=await mcp_call(...); v['verdict']  -> that crashes ('str' has no attribute 'get').",
        "  - get_primitives_library()                                  [native]  exact primitive keys+params",
        "  - await validate(P)   (== mcp_call('host_tools','validate_plan', plan=P), parsed)  schema gate",
        "  - await mcp_call('host_tools','load_skill', topic='freeform')   how to author a 'custom' step from the CadQuery KB",
        "  - cadquery_search / cadquery_doc / cadquery_example on 'host_tools'   the CadQuery KB (used by freeform)",
        "  - v = await build_verify(P)   (== parsed mcp_call('geometry_kernel','build_verify_render', plan=P))",
        "        -> the REAL kernel builds+verifies host-side. Returns the verdict + per-check report,",
        "           or, on a build error, the failing step id and its error. This is your ground truth.",
        "        EXACT CONTRACT: the tool is 'build_verify_render' (ONE underscore); pass plan=P ONLY",
        "        (the kernel derives bbox + part count; there is NO render_format); on PASS read the",
        "        token from v['verification_token'] (NOT v['token']). REMEMBER to PARSE (use build_verify).",
        "",
        "LOOP:",
        "  1. Draft (or revise) plan P as a Python dict. Prefer primitives; 'custom' only when none fits.",
        "  2. r = await validate(P). If not r['valid'], fix EXACTLY",
        "     r['errors'] using r['valid_primitive_types'] and repeat. Never invent a primitive name.",
        "  3. v = await build_verify(P)",
        "     (the kernel derives the declared bbox + part count from P itself — you don't pass them).",
        "     You do NOT compute the overall size: the kernel MEASURES it and returns v['measured_bbox'];",
        "     set each PART's dimensions exactly, the overall extent is emergent and host-recorded.",
        "  4. Read v. If it reports a build failure, the named step's geometry is wrong — reason about WHY",
        "     (look up the op in the CadQuery KB if it is a custom step), fix that step, go to 1.",
        "     If v['verdict']=='FAIL', read v['report']['checks'] and reason about the GEOMETRIC cause",
        "     (open shell -> not watertight; parts not touching -> not coherent, the report names the",
        "     isolated part; overlaps -> self-intersections). Fix the real cause, go to 1.",
        "     If v['verdict']=='PASS', a token is ISSUED. v['fidelity'] is ADVISORY (it sets v['trust_tier']",
        "     = 'certified' or 'needs_review') and NEVER blocks the token — a sound+coherent model is always",
        "     deliverable. You MAY embed the token and FINAL now, OR (if v['trust_tier']=='needs_review' and",
        "     you have budget) refine the form toward 'certified' without dropping requested features, then",
        "     re-verify. To FINAL: take v['verification_token'], set P['verification_token']=that token (do",
        "     NOT change anything else in P), and FINAL(P).",
        "     Every v also carries v['next_action'] — read it; it gives you deterministic, escalating",
        "     guidance (e.g. 'same check failed twice — change strategy', or 'PASS — embed token and FINAL').",
        "",
        "CRITICAL RULE — THE TOKEN CONTRACT (this is enforced by the host, not optional):",
        "  The ONLY way to FINAL is: call build_verify_render, get verdict=='PASS', copy the returned",
        "  'verification_token' verbatim into P['verification_token'], and FINAL that EXACT plan. The host",
        "  re-checks the token against the plan; a MISSING, FABRICATED, or ALTERED-PLAN token is rejected",
        "  and the entire run is DISCARDED. You cannot guess or invent the token — it is signed with a",
        "  secret you do not have. So there is no shortcut: you MUST actually build+verify to finish.",
        "",
        "SUB-AGENTS: whether/how to spawn (llm_query/batch_llm_query) is your call; if you delegate",
        "  geometry work you MUST grant the child mcp=['geometry_kernel','host_tools'] (children inherit",
        "  none) so it can build/verify — see skills/core.md. Otherwise just build it yourself here.",
        "",
        "TERMINATION (you have NO fixed retry count — you self-govern; see skills/core.md):",
        "  - SUCCESS: verdict PASS and faithful to the request -> FINAL(P).",
        "  - BUDGET: your step banner shows remaining calls; before they run out, FINAL the best PASSing",
        "    candidate you have. Never get force-stopped with nothing FINAL'd.",
        "  - NO-PROGRESS: if the SAME check fails after TWO genuinely different strategies, stop repeating —",
        "    pivot strategy, or FINAL the best sound candidate and record the residual issue in 'assumptions'.",
        "  - IMPOSSIBLE: if two requirements cannot both hold, do not loop — FINAL the closest sound plan",
        "    and state the contradiction in 'assumptions'.",
        "",
        "Placement: parts that touch MUST use 'attach' (relational mate), never guessed 'position'.",
        "Repeated features = repeated steps with same parameters, different attach/position.",
        "Build like a REAL manufactured part: ROUND/CONTOUR/HOLLOW — compose `fillet`/`chamfer`/`shell`",
        "modifier verbs (they refine the running solid; place them AFTER the steps they refine) and the",
        "contour builders (lofted_box / revolved_profile / swept_circle). Do NOT leave sharp blocky boxes;",
        "use 'custom' only for a genuinely unique shape no primitive or verb can express.",
        "trust_tier 'needs_review' is EXPECTED for plans with custom steps — it is not a failure.",
        "",
        "ONE COHERENT OBJECT: build_verify_render also checks coherence + fidelity.",
        "  - A real multi-part object (chair, gearbox, bracket+bolt) is an `assembly`: set assembly_kind",
        "    ='assembly', give each part a `part` name, and `attach` every part so they all TOUCH and form",
        "    ONE connected object. Do NOT fuse everything into a single blob, and do NOT leave parts",
        "    floating. A monolithic part (a single machined body) is `single_solid` (one fused component).",
        "  - CONNECTIVITY: every part that belongs to the object MUST reach the rest via an `attach` chain",
        "    (caster->leg, leg->hub, hub->column, column->seat, ...). NEVER hand-compute absolute",
        "    coordinates for a part that must connect — that is how parts end up floating. `attach.offset`",
        "    only slides ACROSS the mating face (in-plane); use `gap` for spacing along the normal.",
        "  - If a part is reported isolated, READ v['next_action']'s 'VISUAL INSPECTION' line (a vision",
        "    description of your rendered model) — it tells you what is floating/disconnected and where —",
        "    then `attach` the named part to the named nearest part of the main body.",
        "  - After geometry passes, the result is RENDERED and a vision critic checks it LOOKS like the",
        "    request. If v['fidelity'] is rejected, you dropped/blobbed a requested feature — add it back",
        "    and re-verify. You cannot get the token by simplifying the object away from the request.",
    ]
    payload = {"role_instructions": "", "task_instructions": chr(10).join(task_lines)}

    # ==========================================
    # Schema (structural for fast-rlm; full Pydantic post-FINAL) — UNCHANGED contract.
    # ==========================================
    pydantic_schema_class = None
    schema_path_str = flags.get("schema")
    schema = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}
    if schema_path_str:
        schema_path = Path(__file__).parent / schema_path_str
        print(f"[INFO] Loading verification schema from: {schema_path_str}")
        if schema_path.suffix == ".py":
            pydantic_schema_class = load_pydantic_schema(schema_path)
            schema = _structural_schema()
        else:
            with open(schema_path) as f:
                schema = json.load(f)

    # ==========================================
    # Tools + skill + primitives guide
    # ==========================================
    tools = get_tools(flags.get("tools"))
    query = payload
    skill_content = ""
    skill_path_str = flags.get("skill")
    if skill_path_str:
        skill_path = Path(__file__).parent / skill_path_str
        if skill_path.exists():
            print(f"[INFO] Loading skill rules from: {skill_path_str}")
            with open(skill_path, "r", encoding="utf-8") as f:
                skill_content = f.read().strip()
    primitives_guide = generate_primitives_summary()
    if primitives_guide:
        skill_content = f"{skill_content}\n{primitives_guide}"
    # Task 4: ground EVERY agent (root + parallel children) on the REAL CadQuery API by injecting a
    # compact, KB-generated "verified idioms" cheat-sheet (signatures + selector grammar + a
    # live-verified "does NOT exist" list). This is what stops the hallucinated custom code
    # (Workplane.taper, wrong spline signature) that wrecked the failing run.
    try:
        import sys as _sys
        _kbtools_dir = str(Path(__file__).parent / "cadquery_kb_pack" / "tools")
        if _kbtools_dir not in _sys.path:
            _sys.path.insert(0, _kbtools_dir)
        from cadquery_kb_tools import build_idioms_skill
        _idioms = build_idioms_skill()
        if _idioms:
            skill_content = f"{skill_content}\n\n{_idioms}"
            print(f"[INFO] Injected verified CadQuery idioms skill ({len(_idioms)} chars).")
    except Exception as e:
        print(f"[INFO] CadQuery idioms skill not injected ({e}); proceeding without it.")
    query["role_instructions"] = skill_content.strip()

    # Single source of truth: the primitive library is injected into the REPL env so the
    # native get_primitives_library() reads it there (the WASM REPL cannot read host files).
    # The host MCP tool and the Pydantic schema read the SAME schemas/primitives.json.
    primitives_file = Path(__file__).parent / "schemas" / "primitives.json"
    primitives_json_text = ""
    if primitives_file.exists():
        with open(primitives_file, "r", encoding="utf-8") as f:
            primitives_json_text = f.read()
        os.environ["PRIMITIVES_JSON_DATA"] = primitives_json_text

    # Per-run signing secret for the unforgeable verification token. It lives ONLY in the
    # geometry_kernel server's env (below) and in THIS process (the gate) — it is NEVER put
    # in env_variables, so it never reaches the model's REPL and cannot be forged.
    run_secret = secrets.token_hex(32)

    # Injected into EVERY REPL (root + sub-agents) so the native primitive tool works.
    # NOTE: deliberately does NOT include run_secret.
    repl_env_variables = {"PRIMITIVES_JSON_DATA": primitives_json_text} if primitives_json_text else None

    # ==========================================
    # MCP servers — v4 wires BOTH: planning tools AND the stateful geometry kernel.
    # ==========================================
    mcp_python = _resolve_mcp_python()

    # The fidelity critic runs HOST-SIDE in the geometry_kernel server. It judges the render
    # against the IMMUTABLE original intent (the user's prompt + the clarifier answers the
    # orchestrator owns) — NOT the agent's self-authored, mutable requirements (which the agent
    # degraded to game the geometric battery). The agent's REPL never receives any of this.
    # Task 1: per-run best-candidate checkpoint file. The geometry kernel server writes the best
    # sound+coherent candidate here; the orchestrator promotes it at run end (even on no-FINAL).
    checkpoint_path = tempfile.mktemp(suffix=".forgecad_ckpt.json")
    if os.path.exists(checkpoint_path):
        try:
            os.unlink(checkpoint_path)
        except Exception:
            pass

    geom_env = {attestation.SECRET_ENV_VAR: run_secret,
                "FORGECAD_CHECKPOINT_FILE": checkpoint_path,
                "FORGECAD_INTENT": json.dumps({"prompt": user_prompt, "clarifications": established_qa})}
    if os.environ.get("RLM_MODEL_API_KEY"):
        geom_env["RLM_MODEL_API_KEY"] = os.environ["RLM_MODEL_API_KEY"]
    if os.environ.get("RLM_MODEL_BASE_URL"):
        geom_env["RLM_MODEL_BASE_URL"] = os.environ["RLM_MODEL_BASE_URL"]
    geom_env["FORGECAD_VISION_MODEL"] = config.get("primary_agent") or "gemini-2.5-pro"
    if reference_image_path and os.path.exists(reference_image_path):
        geom_env["FORGECAD_REFERENCE_IMAGE"] = str(reference_image_path)
    # P2: in the NO-IMAGE case, pass the reasoned form brief so the (otherwise weak "recognizable?")
    # critic judges structure/proportion/refinement against it. NOT set when an image is present —
    # the with-image grounded review is untouched. Advisory only (never blocks the token).
    if _text_form_brief:
        geom_env["FORGECAD_FORM_BRIEF"] = _text_form_brief
    # P5: a deterministic max-envelope guard for an EXPLICIT user-stated size (a non-negotiable).
    _size_constraint = _extract_size_constraint(user_prompt, established_qa)
    if _size_constraint:
        geom_env["FORGECAD_SIZE_CONSTRAINT"] = json.dumps(_size_constraint)
        print(f"[size] enforcing max-envelope {_size_constraint['max_extent_mm']} mm "
              f"(from user-stated '{_size_constraint['source']}').")

    mcp_servers = {
        "host_tools": {
            "command": mcp_python,
            "args": [str(Path(__file__).parent / "tools" / "host_mcp.py")],
        },
        "geometry_kernel": {
            "command": mcp_python,
            "args": [str(Path(__file__).parent / "cad_kernel" / "geometry_server.py")],
            # secret (token signing) + immutable intent + creds for the host-side fidelity critic.
            "env": geom_env,
        },
    }

    print("Starting fast-rlm run (stateful build/verify loop)...")
    prefix = flags.get("prefix", "geometry_planning")
    try:
        result = fast_rlm.run(
            query=query, prefix=prefix, config=config, llm_kwargs=llm_kwargs or None,
            output_schema=schema, tools=tools, mcp_servers=mcp_servers,
            env_variables=repl_env_variables,
            verbose=flags.get("verbose", True),
        )
    except PipelineError:
        raise
    except Exception as e:
        # C4: the engine RAISES when the agent exhausts its call budget WITHOUT a FINAL (and on other
        # fatal engine errors). All post-run code below — including checkpoint promotion — would be
        # skipped. But a sound + coherent candidate may already be BANKED in the checkpoint by the
        # kernel during the run. Deliver it (agent-independent), then fail honestly. This is what
        # makes "never deliver nothing when a PASS existed" hold even on budget exhaustion.
        _fail(f"fast-rlm run ended without a FINAL ({type(e).__name__}: {e}).",
              None, checkpoint_path=checkpoint_path)
    log_file = result.get("log_file")
    plan_dict = result.get("results")

    if not isinstance(plan_dict, dict):
        _fail("The agent did not FINAL a plan dict.", log_file, checkpoint_path=checkpoint_path)

    # ==========================================
    # TOKEN GATE — authenticity. The plan MUST carry a verification_token that could only
    # have come from a genuine build_verify_render PASS for THIS exact plan. This is what
    # makes the in-loop build/verify unskippable: a tokenless or forged FINAL is discarded.
    # Authenticate BEFORE we inject orchestrator-owned clarifications (which would change
    # the plan); the agent FINAL'd the exact plan it verified, so the token matches here.
    # ==========================================
    token = plan_dict.pop(attestation.TOKEN_FIELD, None)
    if not attestation.verify_token(run_secret, plan_dict, token):
        _fail(
            "FINAL plan carries no valid verification_token: it was not proven via a "
            "build_verify_render PASS, or it was altered after verifying. The run is discarded. "
            "The agent must build+verify the plan and embed the returned token unchanged.",
            log_file, plan_dict=plan_dict, checkpoint_path=checkpoint_path)
    print("[INFO] Verification token authenticated — the plan was genuinely built + verified in-loop.")

    # The orchestrator owns the real clarifications by construction (applied AFTER the token
    # gate, since clarifications are non-geometric and must not affect token authentication).
    if established_qa:
        plan_dict["clarifications"] = established_qa

    # ==========================================
    # AUTHORITATIVE host gate — ONE build + verify (same battery the agent used in-loop).
    # No repair loop: the agent already converged in-loop. If this fails, surface it honestly.
    # ==========================================
    if pydantic_schema_class is not None:
        try:
            pydantic_schema_class(**plan_dict)
            print("[INFO] Schema post-validation passed.")
        except Exception as ve:
            msg = "; ".join(
                f"{'.'.join(str(x) for x in e.get('loc', []))}: {e.get('msg','')}"
                for e in (ve.errors() if hasattr(ve, "errors") else [{"loc": [], "msg": str(ve)}])
            )
            _fail(f"FINAL plan failed schema validation (agent should have caught this in-loop): {msg}", log_file, plan_dict=plan_dict, checkpoint_path=checkpoint_path)

    print("\n" + "=" * 40 + "\nPLAN ACCEPTED — AUTHORITATIVE BUILD GATE\n" + "=" * 40)
    declared_bbox = _declared_bbox(plan_dict)
    if declared_bbox:
        print(f"Declared bounding box: {declared_bbox}")

    build_result = None
    try:
        build_result = kernel.build_plan(plan_dict)
    except Exception as e:
        _fail(f"Authoritative build raised an unexpected error: {type(e).__name__}: {e}",
              log_file, checkpoint_path=checkpoint_path)
    if not build_result["ok"]:
        fs = build_result.get("failed_step")
        si = next((s for s in build_result["steps"] if s.get("sequence_id") == fs), {})
        _fail(f"Authoritative build failed at step {fs}: {si.get('error', build_result.get('error'))}", log_file, checkpoint_path=checkpoint_path)

    solid = build_result["solid"]
    print(f"Build OK — {len(build_result['steps'])} step(s).")
    _meta = build_result.get("meta", {})
    try:
        verify_report = verify_mod.verify_solid(
            solid, declared_bbox=declared_bbox,
            expected_components=_meta.get("part_count", 1),
            plan=plan_dict, part_solids=_meta.get("part_solids"),
            fusion_audit=_meta.get("fusion_audit"),
            size_constraint=_size_constraint)
    except Exception as e:
        _fail(f"Authoritative verify raised an unexpected error: {type(e).__name__}: {e}",
              log_file, checkpoint_path=checkpoint_path)
    print(f"Verdict: {verify_report['verdict']}")
    for c in verify_report["checks"]:
        print(f"  {'PASS' if c['passed'] else 'FAIL'} {c['name']}: {c['detail']}")
    if verify_report["verdict"] != "PASS":
        _fail("Authoritative verify FAILED: " + (verify_report.get("localized_fix") or "see checks"),
              log_file, checkpoint_path=checkpoint_path)

    # The bounding box is an OUTPUT the kernel owns: record the MEASURED extent into the plan
    # authoritatively (the agent only ever gave a rough estimate; it never hand-computes the
    # emergent overall size). Safe w.r.t. the token — overall_dimensions is excluded from the hash.
    _mb = verify_report.get("measured_bbox") or verify_report.get("measurements", {}).get("bbox")
    if _mb and len(_mb) == 3:
        plan_dict["overall_dimensions"] = {"width": round(_mb[0], 3),
                                           "length": round(_mb[1], 3),
                                           "height": round(_mb[2], 3)}
        print(f"Measured bounding box (recorded): {plan_dict['overall_dimensions']}")

    # ==========================================
    # Render + export (only after PASS)
    # ==========================================
    base = f"output_{plan_dict.get('title', 'untitled').replace(' ', '_')[:60]}"
    render_dir = Path(__file__).parent / "renders"; render_dir.mkdir(exist_ok=True)
    rendered = None
    try:
        rendered = render_mod.render_solid(solid, str(render_dir / f"{base}.png"))
        print(f"Render: {rendered}")
    except Exception as e:
        print(f"Render warning (non-fatal): {e}")

    export_dir = Path(__file__).parent / "exports"; export_dir.mkdir(exist_ok=True)
    import cadquery as cq
    try:
        cq.exporters.export(solid, str(export_dir / f"{base}.stl"))
        cq.exporters.export(solid, str(export_dir / f"{base}.step"))
        print(f"Exported: {export_dir / (base + '.stl')} , {export_dir / (base + '.step')}")
    except Exception as e:
        print(f"Export warning: {e}")

    # Persist the accepted plan (inter-run state): enables `FORGECAD_EDIT=<id|latest>` next time.
    try:
        saved = plan_store.save_plan(plan_dict, plan_dict.get("title"))
        print(f"Saved plan to store: id={saved['id']} (reuse with FORGECAD_EDIT={saved['id']} or =latest)")
    except Exception as e:
        print(f"Plan-store save warning (non-fatal): {e}")

    trust_tier = "needs_review" if plan_dict.get("contains_freeform", False) else "certified"
    # Success: the agent FINAL'd a verified plan, so the checkpoint is no longer needed.
    try:
        if os.path.exists(checkpoint_path):
            os.unlink(checkpoint_path)
    except Exception:
        pass
    print("\n" + "=" * 40 + "\nPIPELINE COMPLETED SUCCESSFULLY\n" + "=" * 40)
    print(f"Title: {plan_dict.get('title', 'Untitled')}")
    print(f"Steps: {len(build_result['steps'])}  Verdict: {verify_report['verdict']}  Trust: {trust_tier}")
    print(f"Usage: {result.get('usage')}")
    if log_file and os.path.exists(log_file):
        print("\n" + "=" * 40 + "\nEXECUTION TRACE\n" + "=" * 40)
        try:
            render_trace(log_file)
        except Exception as e:
            print(f"trace render failed: {e}")

    return {
        "ok": True,
        "title": plan_dict.get("title", "Untitled"),
        "verdict": verify_report["verdict"],
        "trust_tier": trust_tier,
        "render": rendered,
        "exports": [str(export_dir / f"{base}.stl"), str(export_dir / f"{base}.step")],
        "log_file": log_file,
    }


class PipelineError(Exception):
    """Raised on an honest, unrecoverable pipeline failure (no silent repair). Carries the log file
    so callers (CLI / UI) can show the trace."""
    def __init__(self, msg, log_file=None):
        super().__init__(msg)
        self.log_file = log_file


def _best_effort_salvage(plan_dict, trust_tier=None):
    """Task 1 (host-side, deterministic): re-build + re-verify a plan and, ONLY if it is
    geometrically SOUND + COHERENT (verdict PASS), export + render + plan-store it, CLEARLY TAGGED
    'best-effort'. A broken/non-coherent plan salvages nothing. Fully guarded — never raises.
    Returns export/render paths, or None. `trust_tier` (from the checkpoint) is recorded so the
    user knows whether the form was fidelity-'certified' or only 'needs_review'."""
    if not isinstance(plan_dict, dict) or not plan_dict.get("primitives_sequence"):
        return None
    try:
        bres = kernel.build_plan(plan_dict)
        if not bres.get("ok"):
            return None
        solid = bres["solid"]
        meta = bres.get("meta", {})
        vrep = verify_mod.verify_solid(
            solid, declared_bbox=_declared_bbox(plan_dict),
            expected_components=meta.get("part_count", 1),
            plan=plan_dict, part_solids=meta.get("part_solids"))
        if vrep.get("verdict") != "PASS":
            return None  # only salvage sound + coherent geometry — never a broken artifact
        base = "besteffort_" + str(plan_dict.get("title", "untitled")).replace(" ", "_")[:50]
        export_dir = Path(__file__).parent / "exports"; export_dir.mkdir(exist_ok=True)
        render_dir = Path(__file__).parent / "renders"; render_dir.mkdir(exist_ok=True)
        outs = []
        try:
            import cadquery as cq
            stl = str(export_dir / f"{base}.stl"); step = str(export_dir / f"{base}.step")
            cq.exporters.export(solid, stl)
            cq.exporters.export(solid, step)
            outs += [stl, step]
        except Exception as e:
            print(f"[best-effort] export warning: {e}")
        try:
            outs.append(render_mod.render_solid(solid, str(render_dir / f"{base}.png")))
        except Exception as e:
            print(f"[best-effort] render warning: {e}")
        # Record the measured bbox + persist as a (clearly-labelled) best-effort plan so it is
        # reviewable / reusable via FORGECAD_EDIT, without ever being treated as agent-certified.
        _mb = vrep.get("measured_bbox")
        if _mb and len(_mb) == 3:
            plan_dict = dict(plan_dict)
            plan_dict["overall_dimensions"] = {"width": round(_mb[0], 3),
                                               "length": round(_mb[1], 3),
                                               "height": round(_mb[2], 3)}
        try:
            saved = plan_store.save_plan(plan_dict, "besteffort_" + str(plan_dict.get("title", "untitled")))
            print(f"[best-effort] saved plan to store: id={saved['id']}")
        except Exception as e:
            print(f"[best-effort] plan-store save warning: {e}")
        print("\n" + "=" * 40)
        print(f"BEST-EFFORT ARTIFACT (NOT agent-confirmed; trust_tier={trust_tier or 'needs_review'})")
        print("=" * 40)
        print("The run did not produce a clean agent-confirmed FINAL, but the BEST candidate built")
        print("during the run is geometrically SOUND + COHERENT. Saving it for your review — it is")
        print("a real, buildable model. If trust_tier='needs_review', the form was not fidelity-")
        print("certified (it may be blocky/approximate). Treat as a strong starting point.")
        for o in outs:
            print(f"  best-effort: {o}")
        return outs or None
    except Exception as e:
        print(f"[best-effort] salvage skipped ({e})")
        return None


def _promote_best_candidate(checkpoint_path):
    """Task 1: deliver the BEST sound+coherent candidate the kernel banked during this run (the
    checkpoint), independent of whether the agent FINAL'd. Reads the per-run checkpoint file the
    geometry server wrote, then salvages that plan. Returns paths or None. Never raises."""
    try:
        if not checkpoint_path:
            print("[best-effort] no checkpoint path configured for this run — nothing to promote.")
            return None
        if not os.path.exists(checkpoint_path):
            print(f"[best-effort] no checkpoint file at {checkpoint_path} — no sound+coherent "
                  "candidate was banked during this run (nothing to deliver).")
            return None
        ckpt = json.loads(Path(checkpoint_path).read_text(encoding="utf-8"))
        plan = ckpt.get("plan")
        if not isinstance(plan, dict):
            print("[best-effort] checkpoint present but malformed — nothing to promote.")
            return None
        print(f"[best-effort] promoting run checkpoint (rank={ckpt.get('rank')}, "
              f"trust_tier={ckpt.get('trust_tier')})")
        return _best_effort_salvage(plan, trust_tier=ckpt.get("trust_tier"))
    except Exception as e:
        print(f"[best-effort] checkpoint promotion skipped ({e})")
        return None


def _fail(msg, log_file, plan_dict=None, checkpoint_path=None):
    """Honest, loud failure — no silent repair. Print the trace, then RAISE (callers decide what to
    do: the CLI exits non-zero; the UI shows the error). Never sys.exit here, so it is safe to call
    from a long-lived server process.

    Task 1: FIRST try to promote the best sound+coherent candidate banked this run (the checkpoint),
    so a rejected/never-FINAL'd run STILL yields the best reviewable artifact instead of nothing.
    Falls back to salvaging the rejected FINAL plan if no checkpoint exists. The failure is still
    raised — this does not turn a failure into a success."""
    print(f"\n[FAILED] {msg}")
    promoted = _promote_best_candidate(checkpoint_path) if checkpoint_path else None
    if not promoted and plan_dict is not None:
        _best_effort_salvage(plan_dict)
    if log_file and os.path.exists(log_file):
        print("\n" + "=" * 40 + "\nEXECUTION TRACE (BEFORE FAILURE)\n" + "=" * 40)
        try:
            render_trace(log_file)
        except Exception as e:
            print(f"trace render failed: {e}")
    raise PipelineError(msg, log_file)


def _structural_schema():
    """Minimal structural JSON schema handed to fast-rlm (full Pydantic runs post-FINAL).
    Identical contract to v3 — kept verbatim so validate_plan and the post check never diverge."""
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short descriptive title"},
            "assembly_kind": {"type": "string", "enum": ["single_solid", "assembly"],
                "description": "single_solid = ONE fused connected body; assembly = several separate parts."},
            "overall_dimensions": {"type": "object", "properties": {
                "width": {"type": "number"}, "length": {"type": "number"}, "height": {"type": "number"}},
                "required": ["width", "length", "height"]},
            "engineering_requirements": {"type": "object", "properties": {
                "functional": {"type": "array", "items": {"type": "string"}},
                "environmental_thermal": {"type": "array", "items": {"type": "string"}},
                "structural": {"type": "array", "items": {"type": "string"}},
                "manufacturing_cost": {"type": "array", "items": {"type": "string"}}},
                "required": ["functional", "environmental_thermal", "structural", "manufacturing_cost"]},
            "assumptions": {"type": "array", "items": {"type": "string"}},
            "clarifications": {"type": "array", "items": {"type": "object", "properties": {
                "question": {"type": "string"}, "answer": {"type": "string"}},
                "required": ["question", "answer"]}},
            "primitives_sequence": {"type": "array", "items": {"type": "object", "properties": {
                "sequence_id": {"type": "integer"},
                "name": {"type": "string"},
                "primitive_type": {"type": "string",
                    "description": "An EXACT key from get_primitives_library(), or 'custom'."},
                "parameters": {"type": "object",
                    "description": ("Primitive: key-value dims matching that primitive's schema exactly. "
                        "Custom (primitive_type='custom'): EXACTLY shape_description (str), "
                        "cadquery_operations (list[str], real KB ids), code_sketch (str: valid CadQuery "
                        "Python binding `result`), declared_dimensions (dict[str,float]).")},
                "operation": {"type": "string", "enum": ["join", "cut", "intersect", "new"]},
                "position": {"type": "array", "items": {"type": "number"},
                    "description": "Absolute [x,y,z] mm — ONLY for un-connected bodies. Connected parts MUST use 'attach'."},
                "rotation": {"type": "array", "items": {"type": "number"}},
                "attach": {"type": "object", "description": "Relational mate (kernel derives coords so parts touch).",
                    "properties": {
                        "to": {"type": ["string", "integer"]},
                        "at": {"type": "string", "description": "anchor on TARGET: a face (top/bottom/left/right/front/back), an edge (e.g. 'top|front'), a corner (e.g. 'top|front|right'), or 'center'"},
                        "my_anchor": {"type": "string", "description": "anchor on THIS part (same grammar; default = opposite of `at`)"},
                        "gap": {"type": "number"},
                        "offset": {"type": "array", "items": {"type": "number"}, "description": "[dx,dy,dz] relative slide AFTER the mate (off-centre placement on the face)"}}},
                "pattern": {"type": "object", "description": "Repeat this feature N times (kernel computes the transforms). Operation must be join/cut/intersect.",
                    "properties": {
                        "kind": {"type": "string", "enum": ["linear", "radial"]},
                        "count": {"type": "integer"},
                        "step": {"type": "array", "items": {"type": "number"}, "description": "linear: [dx,dy,dz] per instance"},
                        "axis": {"type": "string", "enum": ["x", "y", "z"], "description": "radial axis"},
                        "center": {"type": "array", "items": {"type": "number"}, "description": "radial: [x,y,z] axis point"},
                        "sweep_deg": {"type": "number", "description": "radial: total sweep (default 360)"}}},
                "part": {"type": "string"},
                "rationale": {"type": "string", "description": "How this step addresses requirements (>15 chars)"}},
                "required": ["sequence_id", "name", "primitive_type", "parameters", "operation", "rationale"]}},
            "contains_freeform": {"type": "boolean"},
            "verification_token": {"type": "string",
                "description": ("MANDATORY. The exact token returned by build_verify_render when it "
                    "returns verdict=='PASS' for THIS plan. Obtain it by calling build_verify_render "
                    "and copy it in verbatim — do NOT fabricate or alter it. A FINAL without a valid "
                    "token is rejected by the host gate and the run is discarded.")},
        },
        "required": ["title", "overall_dimensions", "engineering_requirements",
                     "assumptions", "clarifications", "primitives_sequence", "verification_token"],
    }


if __name__ == "__main__":
    main()
