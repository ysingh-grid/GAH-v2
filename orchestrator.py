"""
rlm.py — Entrypoint to run fast-rlm.

Responsibilities:
  1. Define a hardcoded prompt payload, model configuration, and validation schema.
  2. Load user-defined tools (Python functions) to expose to the REPL.
  3. Invoke fast_rlm.run(...) to execute the recursive LLM loop.
  4. Output result and token usage stats.
"""

import os
import yaml
import json
import sys
import importlib.util
from pathlib import Path
from dotenv import load_dotenv
import fast_rlm
from tools import get_tools
from trace_view import render_trace
from cad_kernel import kernel, verify as verify_mod, render as render_mod

# Load environment variables from the .env file
load_dotenv()

# ==========================================
# 1. Credentials & Endpoint Setup
# ==========================================
# Ensure required environment variables are set before running
if not os.environ.get("RLM_MODEL_API_KEY"):
    raise RuntimeError("RLM_MODEL_API_KEY is missing. Please set it in your .env file.")

api_key = os.environ.get("RLM_MODEL_API_KEY", "")

# ==========================================
# 2. Main Execution
# ==========================================
DEFAULT_CONFIG_PATH = Path(__file__).parent / "run.yaml"

# Determine the model base URL: explicit env > run.yaml > auto-detect known key prefixes.
# We load the yaml here for the base-URL check; main config loading happens in load_run_config().
_cfg_preview = yaml.safe_load(open(DEFAULT_CONFIG_PATH)) or {} if DEFAULT_CONFIG_PATH.exists() else {}
_model_base_url = os.environ.get("RLM_MODEL_BASE_URL") or _cfg_preview.get("model_base_url")
if not _model_base_url:
    # Auto-detect well-known Gemini key prefixes as a hint (not a hard guarantee).
    _GEMINI_KEY_PREFIXES = ("AIzaSy", "AQ.")
    if any(api_key.startswith(p) for p in _GEMINI_KEY_PREFIXES):
        _model_base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
if _model_base_url:
    os.environ["RLM_MODEL_BASE_URL"] = _model_base_url
    print(f"[INFO] Using model base URL: {_model_base_url}")



CONFIG_KEYS = {
    "primary_agent", "sub_agent", "max_depth", "max_calls_per_subagent",
    "truncate_len", "max_money_spent", "max_completion_tokens",
    "max_prompt_tokens", "api_max_retries", "api_timeout_ms",
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
    """Dynamically load a Pydantic model from a Python file path."""
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

    # Strategy 1: Look for a class matching the module name (normalized)
    normalized_module = module_name.replace("_", "").lower()
    for name, model in models.items():
        if name.lower() == normalized_module:
            return model

    # Strategy 2: Identify root models (models not referenced by any other model)
    referenced = set()
    for name, model in models.items():
        for field_name, field in model.model_fields.items():
            annotation = field.annotation
            if annotation:
                annotation_str = str(annotation)
                for other_name in models:
                    if other_name != name and other_name in annotation_str:
                        referenced.add(other_name)

    roots = [name for name in models if name not in referenced]
    if roots:
        return models[roots[0]]

    # Fallback to the alphabetical first model
    return models[sorted(models.keys())[0]]



# Maps invented/colloquial names → the real registry key and a note.
# These are the historically observed confusable pairs from live runs.
_CONFUSABLE_PAIRS = {
    "rounded_box":        ("filleted_box",     "box with rounded/filleted edges"),
    "tube":               ("hollow_cylinder",  "hollow cylindrical tube"),
    "pipe":               ("hollow_cylinder",  "hollow cylindrical pipe"),
    "plate":              ("box",               "flat plate or slab"),
    "polygon":            ("prism",             "extruded regular polygon"),
    "polygon_extrusion":  ("prism",             "extruded regular polygon"),
    "beveled_box":        ("chamfered_box",     "box with chamfered/beveled edges"),
    "donut":              ("torus",             "torus/donut shape"),
    "flat_ring":          ("ring",              "flat concentric ring"),
}

# Param-key remaps for the aliases where the mapping is unambiguous, so normalization
# produces an immediately-valid step (no LLM repair cycle needed).
_ALIAS_PARAM_MAP = {
    "rounded_box": {"radius": "fillet_val"},
    "beveled_box": {"radius": "chamfer_val", "bevel": "chamfer_val"},
}


def normalize_aliases(plan: dict):
    """Deterministically remap known invalid primitive aliases (e.g. rounded_box ->
    filleted_box) to real primitives BEFORE validation. Fixes the single most common
    model mistake instantly, with NO extra LLM call — keeping runs fast. Anything this
    can't fix falls through to the bounded validation-repair loop. Returns (plan, notes)."""
    notes = []
    for step in plan.get("primitives_sequence", []) or []:
        pt = step.get("primitive_type")
        if pt in _CONFUSABLE_PAIRS:
            real = _CONFUSABLE_PAIRS[pt][0]
            params = step.get("parameters", {}) or {}
            for old, new in _ALIAS_PARAM_MAP.get(pt, {}).items():
                if old in params and new not in params:
                    params[new] = params.pop(old)
            step["primitive_type"] = real
            step["parameters"] = params
            notes.append(f"step {step.get('sequence_id')}: '{pt}' -> '{real}'")
    return plan, notes


def generate_primitives_summary():
    """Generate a compact primitive reference (names + param keys only).
    The agent can call get_primitives_library() for full parameter schemas.
    Kept short deliberately — the full table was ~1,490 tokens re-sent every LLM call;
    this compact version is ~486 tokens with the same navigational value.
    Confusable-pair annotations added to steer the model toward the real name
    at the point in the prompt where it reads the list."""
    primitives_path = Path(__file__).parent / "schemas" / "primitives.json"
    if not primitives_path.exists():
        return ""

    with open(primitives_path, "r", encoding="utf-8") as f:
        primitives = json.load(f)

    # Build a reverse map: real_name → list of colloquial aliases that must NOT be used
    _real_to_aliases: dict[str, list[str]] = {}
    for alias, (real, _) in _CONFUSABLE_PAIRS.items():
        _real_to_aliases.setdefault(real, []).append(alias)

    lines = [
        "\n### 🧱 Available Geometric Primitives (EXACT keys — use nothing else)",
        "Call `get_primitives_library()` to get full parameter schemas "
        "and defaults. Prefer primitives over custom steps — they are fully verifiable. "
        "Use a `custom` step only when NO primitive can represent the shape.",
        "",
    ]
    for name, data in sorted(primitives.items()):
        desc = data.get("description", "").split(".")[0]  # first sentence only
        params = ", ".join(data.get("parameters", {}).keys())
        base = f"  **{name}** [{params}] — {desc}"
        aliases = _real_to_aliases.get(name, [])
        if aliases:
            alias_str = ", ".join(f'"{a}"' for a in aliases)
            base += f"  ← use this, NOT {alias_str}"
        lines.append(base)

    lines.append("")
    lines.append("  ⚠️  The following names do NOT exist — if you use them the plan is rejected:")
    for alias, (real, meaning) in sorted(_CONFUSABLE_PAIRS.items()):
        lines.append(f'    "{alias}" → use **{real}** instead ({meaning})')

    return "\n".join(lines)

CLARIFIER_ROLE = (
    "You are a CAD requirements analyst. Given a design request, identify the FEW "
    "genuinely critical unknowns a designer must resolve before modelling — things "
    "where a wrong guess forces a redesign (overall size/footprint, mounting or bolt "
    "interface, sealing/IP rating, load path, count of major features). Ignore benign "
    "details that have safe standard defaults. Output STRICT JSON: "
    '{"questions": ["...", "..."]} with AT MOST 3 short, specific questions, or '
    '{"questions": []} if the request is already well-specified. Ask nothing else.'
)


def gather_clarifications(user_prompt, config, llm_kwargs, flags):
    """Dedicated pre-planning pass: surface up to 3 critical questions, ASK the user,
    and return real Q&A. This runs as its OWN single-purpose model call, so asking
    cannot be skipped by the planning agent. Fully fail-safe: any problem -> [] and
    planning proceeds without clarifications (never blocks, never crashes)."""
    if not flags.get("clarify", True):
        return []
    try:
        from tools.clarify_io import ask_user_impl, UNANSWERED
    except Exception as e:
        print(f"[clarify] disabled (io import failed: {e})")
        return []
    questions = []
    try:
        q_schema = {"type": "object",
                    "properties": {"questions": {"type": "array", "items": {"type": "string"}}},
                    "required": ["questions"]}
        clar_cfg = dict(config or {})
        clar_cfg["max_depth"] = 0  # single shot, no recursion/tools needed
        res = fast_rlm.run(
            query={"role_instructions": CLARIFIER_ROLE,
                   "task_instructions": f"Design request: '{user_prompt}'."},
            prefix="clarifier", config=clar_cfg, llm_kwargs=llm_kwargs or None,
            output_schema=q_schema, verbose=False)
        questions = ((res.get("results") or {}).get("questions") or [])[:3]
    except Exception as e:
        print(f"[clarify] question pass skipped ({e}); planning will proceed without it.")
        questions = []

    # Deterministic guarantee: if the model surfaced NO questions but the prompt is clearly
    # under-specified (contains no dimensions/quantities at all), ask ONE consolidated
    # question, so a vague request like "design an office chair" is never silently guessed.
    import re as _re
    if not questions and not _re.search(r"\d", user_prompt or ""):
        questions = ["This request doesn't specify key parameters. What should I design to — "
                     "overall size (mm), load/weight capacity, material, and any required "
                     "features? (reply with specifics, or 'use sensible defaults')"]
        print("[clarify] prompt is under-specified — asking one consolidated question.")

    qa = []
    for q in questions:
        q = (q or "").strip()
        if not q:
            continue
        print(f"[clarify] asking: {q}")
        ans = ask_user_impl(q)
        if ans and not ans.startswith("[UNANSWERED"):
            qa.append({"question": q, "answer": ans})
    if qa:
        print(f"[clarify] gathered {len(qa)} answer(s) from the user.")
    return qa


def main():
    # Clear live clarification session log file for the new run
    asked_file = Path(__file__).parent / ".asked_clarifications.json"
    if asked_file.exists():
        try:
            asked_file.unlink()
        except Exception:
            pass


    # ==========================================
    # 3. Load Configurations
    # ==========================================
    config, llm_kwargs, flags = load_run_config()

    print("\n--- Geometry Agent Harness: Plan Stage ---")
    user_prompt = input("Enter your CAD design request (or press enter for default: 'Design a mounting bracket for a camera enclosure to be mounted outdoors on a brick wall'): ")
    if not user_prompt.strip():
        user_prompt = "Design a mounting bracket for a camera enclosure to be mounted outdoors on a brick wall"

    # Dedicated clarification pass BEFORE planning (asking cannot be skipped here).
    established_qa = gather_clarifications(user_prompt, config, llm_kwargs, flags)
    _established_block = ""
    if established_qa:
        _facts = chr(10).join(f"  - {c['question']} -> {c['answer']}" for c in established_qa)
        _established_block = ("These requirements were ALREADY clarified with the user; "
                              "treat them as given facts:" + chr(10) + _facts)

    _task_lines = [
        f"The user wants to design: '{user_prompt}'.",
        "",
        _established_block,
        "",
        "Produce ONE GeometryPlan that PASSES the validate_plan tool, then FINAL it.",
        "Work in your REPL, one tool call per block, waiting for output each time:",
        "  1. prims = get_primitives_library()          [native, no await] — see exact primitive keys + params.",
        "  2. Draft the plan (pure Python dict). Prefer primitives; for a shape NO primitive can represent,",
        "     use a 'custom' step (call load_skill(topic='freeform') for how). Repeated features (legs, holes,",
        "     fins) = repeated steps with the SAME parameters and different position/rotation.",
        "  3. report = await mcp_call('host_tools', 'validate_plan', plan=draft_plan)",
        "     If report['valid'] is False, fix exactly report['errors'] (use report['valid_primitive_types']) and",
        "     call validate_plan again. Do not proceed until valid is True.",
        "  4. FINAL(draft_plan)  — only after validate_plan returned valid=True.",
        "",
        "Rules:",
        "  - Every primitive_type MUST be 'custom' or an EXACT key from get_primitives_library(); never invent one.",
        "  - Do NOT call llm_query() or spawn sub-agents (it can recurse and crash the run).",
        "  - trust_tier 'needs_review' is EXPECTED and correct for plans containing custom steps; it is not a failure.",
        "  - CRITICAL FOR ASSEMBLIES: Every step EXCEPT the first base piece MUST use 'attach' to connect to a previous piece. Do NOT guess absolute 'position' coordinates for connected pieces, or they will float in the air and your plan will be REJECTED."
    ]
    payload = {
        "role_instructions": "",
        "task_instructions": chr(10).join(_task_lines),
    }

    # ==========================================
    # 4. Load Output Verification Schema
    # ==========================================
    pydantic_schema_class = None
    schema_path_str = flags.get("schema")
    if schema_path_str:
        schema_path = Path(__file__).parent / schema_path_str
        print(f"[INFO] Loading verification schema from: {schema_path_str}")
        if schema_path.suffix == ".py":
            pydantic_schema_class = load_pydantic_schema(schema_path)
            # Use a minimal structural schema for fast_rlm to avoid massive token bloat
            # from inlining 18 primitive parameters. Full Pydantic validation runs post-FINAL.
            schema = {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short descriptive title of the design project"
                    },
                    "assembly_kind": {
                        "type": "string",
                        "enum": ["single_solid", "assembly"],
                        "description": "single_solid = ONE fused connected body (use mates/attach so parts touch); assembly = several distinct separate parts (each gets a `part` name and is verified separately). Default single_solid."
                    },
                    "overall_dimensions": {
                        "type": "object",
                        "properties": {
                            "width": {"type": "number", "description": "Overall width of the bounding box in mm"},
                            "length": {"type": "number", "description": "Overall length of the bounding box in mm"},
                            "height": {"type": "number", "description": "Overall height of the bounding box in mm"}
                        },
                        "required": ["width", "length", "height"]
                    },
                    "engineering_requirements": {
                        "type": "object",
                        "properties": {
                            "functional": {"type": "array", "items": {"type": "string"}},
                            "environmental_thermal": {"type": "array", "items": {"type": "string"}},
                            "structural": {"type": "array", "items": {"type": "string"}},
                            "manufacturing_cost": {"type": "array", "items": {"type": "string"}}
                        },
                        "required": ["functional", "environmental_thermal", "structural", "manufacturing_cost"]
                    },
                    "assumptions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "A list of assumed default values or decisions made for under-specified parameters"
                    },
                    "clarifications": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "question": {"type": "string"},
                                "answer": {"type": "string"}
                            },
                            "required": ["question", "answer"]
                        },
                        "description": "Log of clarifying questions asked to the user and their replies using the ask_user tool."
                    },
                    "primitives_sequence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "sequence_id": {"type": "integer", "description": "1-based order of execution"},
                                "name": {"type": "string", "description": "Descriptive name of the part or step"},
                                "primitive_type": {
                                    "type": "string",
                                    "description": "The primitive name (e.g. 'box', 'cylinder', 'cone', 'sphere', 'torus', 'wedge', 'custom'). Call get_primitives_library() to see all supported primitive names."
                                },
                                "parameters": {
                                    "type": "object",
                                    "description": (
                                        "Parameters for this step. "
                                        "For a PRIMITIVE step: key-value dims matching that primitive's schema exactly "
                                        "(call get_primitives_library() to see the exact keys, e.g. {'width':10,'height':50}). "
                                        "For a CUSTOM step (primitive_type='custom'): MUST be a dict with EXACTLY these keys — "
                                        "no others, no aliases: "
                                        "shape_description (str: plain-words description of what this step builds), "
                                        "cadquery_operations (list[str]: CadQuery operation ids actually used, e.g. "
                                        "['Workplane.polyline','Workplane.extrude'] — look up via cadquery_search; never invent), "
                                        "code_sketch (str: CRITICAL! MUST be the actual valid Python source code using CadQuery that builds this shape and binds it to `result`. Do NOT write English text or pseudocode here! Example: `result = cq.Workplane('XY').extrude(10)`), "
                                        "declared_dimensions (dict[str,float]: key dimensions you intend to build, "
                                        "e.g. {'arm_length_mm': 200, 'arm_count': 5}). "
                                        "WRONG: {'description':'...', 'code_sketch': 'A sketch is extruded...'} — CORRECT: {'shape_description':'...', "
                                        "'cadquery_operations':[...], 'code_sketch':'...', 'declared_dimensions':{...}}"
                                    )
                                },
                                "operation": {
                                    "type": "string",
                                    "enum": ["join", "cut", "intersect", "new"],
                                    "description": "Boolean combination operation: 'join', 'cut', 'intersect', or 'new'"
                                },
                                "position": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                    "description": "[x, y, z] mm translation. CRITICAL WARNING: DO NOT guess absolute coordinates for parts that must connect. You will cause floating-point gaps and broken assemblies. For connected pieces, you MUST use 'attach' and leave 'position' empty. This field should ONLY be used for entirely disconnected free-floating bodies."
                                },
                                "rotation": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                    "description": "[rx, ry, rz] degrees rotation applied to this step before combining (default [0,0,0])"
                                },
                                "attach": {
                                    "type": "object",
                                    "description": "RELATIONAL placement: mate this part to another instead of guessing absolute coordinates. The kernel derives the position so they touch. This MUST be used for parts that connect.",
                                    "properties": {
                                        "to": {"type": ["string", "integer"], "description": "Target step: its name or sequence_id"},
                                        "at": {"type": "string", "enum": ["top","bottom","left","right","front","back","center"], "description": "Anchor on the TARGET part"},
                                        "my_anchor": {"type": "string", "enum": ["top","bottom","left","right","front","back","center"], "description": "Anchor on THIS part (defaults to opposite of `at`)"},
                                        "gap": {"type": "number", "description": "mm gap along the mate normal; 0 = touching"}
                                    }
                                },
                                "part": {
                                    "type": "string",
                                    "description": "Assembly part name this step belongs to (only used when assembly_kind='assembly')"
                                },
                                "rationale": {
                                    "type": "string",
                                    "description": "Detailed explanation of how this step addresses requirements (must be >15 characters)"
                                }
                            },
                            "required": ["sequence_id", "name", "primitive_type", "parameters", "operation", "rationale"]
                        },
                        "description": "Step-by-step sequence of CAD steps representing the build order. Use primitive steps where a primitive fits; use a 'custom' freeform CadQuery step where no primitive can represent the shape."
                    },
                    "contains_freeform": {
                        "type": "boolean",
                        "description": "Set to True if any step is a freeform 'custom' step, meaning the plan ships at trust tier needs_review."
                    }
                },
                "required": [
                    "title",
                    "overall_dimensions",
                    "engineering_requirements",
                    "assumptions",
                    "clarifications",
                    "primitives_sequence"
                ]
            }
        else:
            with open(schema_path) as f:
                schema = json.load(f)
    else:
        # Fallback to the default hardcoded schema if no file is specified
        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short descriptive title of the design project"},
                "assumptions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "assumptions"]
        }

    # ==========================================
    # 5. Load Tools
    # ==========================================
    tools = get_tools(flags.get("tools")) 

    # --- Prepend Skill Description and Primitives Guide to Payload ---
    query = payload
    skill_path_str = flags.get("skill")
    skill_content = ""
    if skill_path_str:
        skill_path = Path(__file__).parent / skill_path_str
        if skill_path.exists():
            print(f"[INFO] Loading skill rules from: {skill_path_str}")
            with open(skill_path, "r", encoding="utf-8") as f:
                skill_content = f.read().strip()
                
    primitives_guide = generate_primitives_summary()
    if primitives_guide:
        skill_content = f"{skill_content}\n{primitives_guide}"

    query["role_instructions"] = skill_content.strip()

    # Pass primitives data into the WASM/Deno sandbox via env var (data transport only).
    primitives_file = Path(__file__).parent / "schemas" / "primitives.json"
    if primitives_file.exists():
        with open(primitives_file, "r", encoding="utf-8") as f:
            os.environ["PRIMITIVES_JSON_DATA"] = f.read()

    print("Starting fast-rlm run...")
    print(f"Payload: {payload}\n")

    # ==========================================
    # 6. Call fast-rlm runner
    # ==========================================
    prefix = flags.get("prefix", "geometry_planning")
    log_file = None
    
    # Find a Python interpreter that has 'mcp' installed for our host MCP server.
    # Strategy: prefer the current interpreter (already validated), then use shutil.which
    # to search PATH for python3/python. Never hardcode user-specific absolute paths.
    import shutil as _shutil
    mcp_python = sys.executable
    try:
        import mcp  # noqa: F401
    except ImportError:
        _candidates = []
        for _name in ["python3", "python"]:
            _found = _shutil.which(_name)
            if _found and _found != sys.executable:
                _candidates.append(_found)
        for candidate in _candidates:
            try:
                import subprocess as _sp
                res = _sp.run([candidate, "-c", "import mcp"], capture_output=True)
                if res.returncode == 0:
                    mcp_python = candidate
                    break
            except Exception:
                continue

    # Configure host-level MCP servers to bypass WASM/Pyodide environment restrictions
    mcp_servers = {
        "host_tools": {
            "command": mcp_python,
            "args": [str(Path(__file__).parent / "tools" / "host_mcp.py")]
        }
    }

    try:
        result = fast_rlm.run(
            query=query,
            prefix=prefix,
            config=config,
            llm_kwargs=llm_kwargs or None,
            output_schema=schema,
            tools=tools,
            mcp_servers=mcp_servers,
            verbose=flags.get("verbose", True),
        )
        log_file = result.get("log_file")
    finally:
        pass

    # Post-validate the results using the python Pydantic schema to catch python-only
    # validation constraints (model validators). The schema validates geometry only,
    # so this is identical to what validate_plan returns in-loop (no hidden divergence).
    # The schema check is UNCONDITIONAL and orchestrator-owned: it does NOT depend on the
    # model having called validate_plan. If the plan is invalid (e.g. an invented
    # primitive_type like 'rounded_box'), we auto-repair — feed the EXACT errors + the list
    # of valid primitive types back to the model, re-plan, and re-validate, bounded. We only
    # raise after repair is exhausted. This is why a model that skips validate_plan and
    # FINALs a bad plan no longer crashes the run.
    def _validate_plan_dict(pd):
        try:
            pydantic_schema_class(**pd)
            return True, []
        except Exception as ve:
            errs = []
            if hasattr(ve, "errors"):
                for er in ve.errors():
                    errs.append({"location": ".".join(str(x) for x in er.get("loc", [])),
                                 "message": er.get("msg", "")})
            else:
                errs = [{"location": "", "message": str(ve)}]
            return False, errs

    try:
        from schemas.geometry_plan import PRIMITIVES_REGISTRY as _PR
        _VALID_TYPES = sorted(list(_PR.keys()) + ["custom"])
    except Exception:
        _VALID_TYPES = []

    plan_dict = result.get("results")

    # Deterministic fast-path: fix known invalid primitive aliases (rounded_box ->
    # filleted_box, etc.) with no LLM call, so the most common error never costs a repair cycle.
    plan_dict, _alias_notes = normalize_aliases(plan_dict)
    if _alias_notes:
        print("[NORMALIZE] auto-corrected invalid primitive aliases: " + "; ".join(_alias_notes))

    if pydantic_schema_class is not None:
        print("[INFO] Post-validating results using CPython Pydantic schema...")
        valid, errors = _validate_plan_dict(plan_dict)
        MAX_V = int(flags.get("max_validation_repair_attempts",
                              flags.get("max_repair_attempts", 3)))
        attempt = 0
        while not valid and attempt < MAX_V:
            attempt += 1
            print(f"[VALIDATION REPAIR {attempt}/{MAX_V}] plan rejected by schema:")
            for e in errors:
                print(f"    - {e['location']}: {e['message']}")
            repair_task = [
                "REPAIR MODE: your previous plan FAILED schema validation. Fix ONLY the listed",
                "errors and return the FULL corrected plan via FINAL(). Keep every valid step as-is.",
                "",
                "VALIDATION ERRORS (location -> message):",
                *[f"  - {e['location']}: {e['message']}" for e in errors],
                "",
                f"VALID primitive_type values — use ONLY these (or 'custom'): {_VALID_TYPES}",
                "If a step used a primitive_type not in that list, it does NOT exist. Replace it with",
                "the nearest real primitive (e.g. a rounded/soft box -> 'filleted_box'; a rounded",
                "cylinder -> 'rounded_cylinder') and make its parameters match that primitive EXACTLY,",
                "or rewrite the step as a 'custom' step. Do not invent names or keys.",
                "",
                "CURRENT PLAN (invalid — fix it):",
                json.dumps(plan_dict, indent=2),
                "",
                "Return FINAL(corrected_plan).",
            ]
            repair_query = {"role_instructions": query["role_instructions"],
                            "task_instructions": "\n".join(repair_task)}
            try:
                rr = fast_rlm.run(query=repair_query, prefix=f"{prefix}_vrepair_a{attempt}",
                                  config=config, llm_kwargs=llm_kwargs or None,
                                  output_schema=schema, tools=tools, mcp_servers=mcp_servers,
                                  verbose=flags.get("verbose", True))
            except Exception as rep_err:
                print(f"[VALIDATION REPAIR {attempt}] repair run errored: {rep_err}")
                break
            cand = rr.get("results")
            valid, errors = _validate_plan_dict(cand)
            if valid:
                print(f"[VALIDATION REPAIR {attempt}] passed — using the corrected plan.")
                plan_dict = cand
                result = rr
                log_file = rr.get("log_file", log_file)

        if not valid:
            print(f"\n[ERROR] Plan failed schema validation after {attempt} repair attempt(s):")
            for e in errors:
                print(f"    - {e['location']}: {e['message']}")
            log_dir = Path(__file__).parent / "logs"
            if log_dir.exists():
                matching_files = list(log_dir.glob(f"{prefix}*_*.jsonl"))
                if matching_files:
                    log_file = str(max(matching_files, key=lambda f: f.stat().st_mtime))
            if log_file:
                print("\n" + "=" * 40 + "\nEXECUTION TRACE (BEFORE FAILURE)\n" + "=" * 40)
                try:
                    render_trace(log_file)
                except Exception as trace_err:
                    print(f"Failed to render trace: {trace_err}")
            raise ValueError("GeometryPlan failed schema validation after repair attempts: "
                             + "; ".join(f"{e['location']}: {e['message']}" for e in errors))
        print("[INFO] Pydantic schema post-validation passed.")
    # The orchestrator gathered the real clarifications, so they are authoritative.
    if established_qa:
        plan_dict["clarifications"] = established_qa

    # ==========================================
    # 7. Build → Verify → Render Pipeline
    # ==========================================
    print("\n" + "=" * 40)
    print("PLAN ACCEPTED — STARTING BUILD PIPELINE")
    print("=" * 40)

    # 7a. Build
    print("\n--- BUILD STAGE ---")
    declared_bbox = None
    ov = plan_dict.get("overall_dimensions")
    if ov:
        declared_bbox = [ov.get("width", 0), ov.get("length", 0), ov.get("height", 0)]
        print(f"Declared bounding box: {declared_bbox}")

    # --- bounded repair loop: re-plan with the SPECIFIC error, rebuild, re-verify.
    # Used for BOTH build failures and verify failures — any stage failure recovers here,
    # nothing crashes mid-pipeline. (Closure over config/query/tools/etc.)
    def _run_repair(plan, failure_msg, failed_step_id):
        MAX_ATTEMPTS = int(flags.get("max_repair_attempts", 3))
        cur = plan
        for attempt in range(1, MAX_ATTEMPTS + 1):
            print(f"\n--- REPAIR ATTEMPT {attempt}/{MAX_ATTEMPTS} --- ({failure_msg[:90]})")
            repair_task = [
                "REPAIR MODE: your plan failed. Fix ONLY the failing step; keep the rest as-is.",
                "",
                f"FAILURE: {failure_msg}",
                f"Failing step sequence_id = {failed_step_id}.",
                "If a custom step's code_sketch was EMPTY, broken, or contained English text instead of code, ",
                "you MUST write the real valid Python source code using CadQuery that builds the shape and binds it to `result`.",
                "If a primitive_type or its parameters were wrong, fix them. Return the FULL corrected plan.",
                "",
                "CURRENT PLAN:",
                json.dumps(cur, indent=2),
                "",
                "Validate, then FINAL(corrected_plan).",
            ]
            rq = {"role_instructions": query["role_instructions"], "task_instructions": "\n".join(repair_task)}
            try:
                rr = fast_rlm.run(query=rq, prefix=f"{prefix}_repair_a{attempt}", config=config,
                                  llm_kwargs=llm_kwargs or None, output_schema=schema, tools=tools,
                                  mcp_servers=mcp_servers, verbose=flags.get("verbose", True))
            except Exception as e:
                print(f"[REPAIR {attempt}] repair run errored: {e}")
                continue
            cand = rr.get("results")
            cand, _ = normalize_aliases(cand)
            ok_v, errs = _validate_plan_dict(cand)
            if not ok_v:
                failure_msg = "schema: " + "; ".join(f"{e['location']}: {e['message']}" for e in errs)
                cur, failed_step_id = cand, 1
                continue
            br = kernel.build_plan(cand)
            if not br["ok"]:
                fs = br.get("failed_step")
                si = next((s for s in br["steps"] if s.get("sequence_id") == fs), {})
                failure_msg = f"build failed at step {fs}: {si.get('error')}"
                cur, failed_step_id = cand, (fs or 1)
                continue
            ov_cand = cand.get("overall_dimensions")
            cand_bbox = [ov_cand.get("width", 0), ov_cand.get("length", 0), ov_cand.get("height", 0)] if ov_cand else declared_bbox
            vr = verify_mod.verify_solid(br["solid"], declared_bbox=cand_bbox,
                                          expected_components=br.get("meta", {}).get("part_count", 1))
            
            failed_checks = [c for c in vr["checks"] if not c["passed"]]
            if len(failed_checks) == 1 and failed_checks[0]["name"] == "bbox_matches_declared":
                measured_bbox = vr["measurements"]["bbox"]
                print(f"[REPAIR {attempt}] [AUTO-SYNC] Bounding box mismatch. Updating plan's overall_dimensions to {measured_bbox}.")
                if "overall_dimensions" not in cand:
                    cand["overall_dimensions"] = {}
                cand["overall_dimensions"]["width"] = measured_bbox[0]
                cand["overall_dimensions"]["length"] = measured_bbox[1]
                cand["overall_dimensions"]["height"] = measured_bbox[2]
                vr["verdict"] = "PASS"
            
            print(f"[REPAIR {attempt}] Verdict: {vr['verdict']}")
            if vr["verdict"] == "PASS":
                return True, cand, br, vr, rr
            failure_msg = vr.get("localized_fix", failure_msg)
            cur, failed_step_id = cand, 1
        return False, cur, None, None, None

    build_result = kernel.build_plan(plan_dict)
    need_repair, failure_msg, failed_sid = False, None, 1
    if not build_result["ok"]:
        failed_sid = build_result.get("failed_step") or 1
        si = next((s for s in build_result["steps"] if s.get("sequence_id") == failed_sid), {})
        failure_msg = f"build failed at step {failed_sid} ({si.get('primitive_type','?')}): {si.get('error','unknown')}"
        print(f"\n[BUILD FAILED] {failure_msg}")
        need_repair = True
    else:
        solid = build_result["solid"]
        print(f"Build OK — {len(build_result['steps'])} step(s) executed successfully.")
        print("\n--- VERIFY STAGE ---")
        verify_report = verify_mod.verify_solid(solid, declared_bbox=declared_bbox,
                                                 expected_components=build_result.get("meta", {}).get("part_count", 1))
        print(f"Verdict: {verify_report['verdict']}")
        for check in verify_report["checks"]:
            print(f"  {'✓' if check['passed'] else '✗'} {check['name']}: {check['detail']}")
        print(f"Measurements: volume={verify_report['measurements']['volume']}mm³, "
              f"bbox={verify_report['measurements']['bbox']}, components={verify_report['measurements']['components']}")
        if verify_report["verdict"] == "FAIL":
            failed_checks = [c for c in verify_report["checks"] if not c["passed"]]
            if len(failed_checks) == 1 and failed_checks[0]["name"] == "bbox_matches_declared":
                measured_bbox = verify_report["measurements"]["bbox"]
                print(f"\n[AUTO-SYNC] Bounding box mismatch. Auto-updating plan's overall_dimensions from {declared_bbox} to {measured_bbox}.")
                if "overall_dimensions" not in plan_dict:
                    plan_dict["overall_dimensions"] = {}
                plan_dict["overall_dimensions"]["width"] = measured_bbox[0]
                plan_dict["overall_dimensions"]["length"] = measured_bbox[1]
                plan_dict["overall_dimensions"]["height"] = measured_bbox[2]
                verify_report["verdict"] = "PASS"
                need_repair = False
            else:
                failed_sid = build_result.get("failed_step") or 1
                failure_msg = verify_report.get("localized_fix", "verification failed")
                print(f"\n[VERIFY FAILED] {failure_msg}")
                need_repair = True

    if need_repair:
        repaired, plan_dict, _br, _vr, _repair_rlm = _run_repair(plan_dict, failure_msg, failed_sid)
        if not repaired:
            print("\n[REPAIR EXHAUSTED] All repair attempts failed — shipping as FAILED.")
            if log_file and os.path.exists(log_file):
                print("\n" + "=" * 40 + "\nEXECUTION TRACE (PLANNING)\n" + "=" * 40)
                try:
                    render_trace(log_file)
                except Exception as te:
                    print(f"Failed to render trace: {te}")
            sys.exit(1)
        build_result, verify_report = _br, _vr
        solid = build_result["solid"]
        if _repair_rlm is not None:
            log_file = _repair_rlm.get("log_file") or log_file
        print("[REPAIR] Succeeded — solid is valid.")
    else:
        solid = build_result["solid"]

    # 7c. Render (only after PASS)
    print("\n--- RENDER STAGE ---")
    render_dir = Path(__file__).parent / "renders"
    render_dir.mkdir(exist_ok=True)
    out_path = str(render_dir / f"output_{plan_dict.get('title', 'untitled').replace(' ', '_')[:60]}.png")
    try:
        rendered = render_mod.render_solid(solid, out_path)
        print(f"Render saved to: {rendered}")
    except Exception as render_err:
        print(f"Render warning (non-fatal): {render_err}")
        rendered = None

    # 7c2. Export CAD files
    print("\n--- EXPORT STAGE ---")
    export_dir = Path(__file__).parent / "exports"
    export_dir.mkdir(exist_ok=True)
    base_filename = f"output_{plan_dict.get('title', 'untitled').replace(' ', '_')[:60]}"
    stl_path = str(export_dir / f"{base_filename}.stl")
    step_path = str(export_dir / f"{base_filename}.step")
    
    import cadquery as cq
    try:
        cq.exporters.export(solid, stl_path)
        cq.exporters.export(solid, step_path)
        print(f"CAD files exported to:\n  - {stl_path}\n  - {step_path}")
    except Exception as export_err:
        print(f"CAD Export warning: {export_err}")
        stl_path = None
        step_path = None

    # 7d. Trust tier
    trust_tier = "needs_review" if plan_dict.get("contains_freeform", False) else "certified"
    print(f"\nTrust tier: {trust_tier}")

    # ==========================================
    # 8. Final Summary
    # ==========================================
    print("\n" + "=" * 40)
    print("PIPELINE COMPLETED SUCCESSFULLY")
    print("=" * 40)
    print(f"Title: {plan_dict.get('title', 'Untitled')}")
    print(f"Steps: {len(build_result['steps'])}")
    print(f"Verdict: {verify_report['verdict']}")
    print(f"Trust: {trust_tier}")
    if rendered:
        print(f"Render: {rendered}")
    print(f"\nPlan log: {log_file}")
    print(f"Usage stats: {result.get('usage')}")

    if log_file and os.path.exists(log_file):
        print("\n" + "=" * 40)
        print("EXECUTION TRACE (PLANNING)")
        print("=" * 40)
        try:
            render_trace(log_file)
        except Exception as trace_err:
            print(f"Failed to render trace: {trace_err}")

if __name__ == "__main__":
    main()
