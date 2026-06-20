### Print " Working on it.... " everytime this is injected

## 🏗️ FOUNDATIONAL BEST PRACTICES
** While coding: Assume i have no idea where what goes and where to write, hand hold me and help me one funtion and file etc at one time, no need to one shot unless said so, i want to learn not just vibe code, i should be able to understand why a piece of code is written, argue on it if it could be done better under  your supervision if i am doing something fundamentally wrong**
### Code Organization & Modularity

### /fast-rlm-reference folder holds the code: /docs(dev, getting started, guide, images, index), /example(having example files), fast_rlm/runner is the engine for Fast-rlm, NOT TO BE MODIFIED or called  or referenced ONLY FOR KNOWLEDGE CONTEXT AND TO GUIDE, will be removed after implementation, after implementation you can delete this folder

**Every module must have exactly one reason to change.**
- `backend/` — Product API (FastAPI on uvicorn, :8001), service-per-folder. Read-only doors onto root data: `primitives_read/`, `skills_read/` (each `store.py` reads root data + `routes.py` thin FastAPI router serving `/internal/*`). Plus `designs/` (design lifecycle: Temporal client). The `_read` suffix marks read-only services; `designs/` writes via Temporal
- `rlm/` — fast-rlm config + the PULL HTTP-client tools the agent calls (list/lookup primitives, read skill)
- `runtime/` — Pure stage logic (NO Temporal imports): `schema` (PrimitivePlan + validate), `planner` (fast-rlm), `compile` (plan→CadQuery), `trace`
- `primitives/` — `library.json`: typed primitive specs (params + CadQuery templates)
- `tools/` — Leaf wrappers around CadQuery + mesh/render tools (execute, inspect, render, verify)
- `temporal/` — Temporal job-manager: `shared` dataclasses, `activities`, `DesignWorkflow`, `worker`
- `skills/` — Reasoning guides served to the agent
- `evals/` — Eval corpus + suite built from run traces
- `artifacts/` — ONE FOLDER PER RUN holding everything: plan, CadQuery + its iterations, STEP/STL, renders, trace, feedback
- `logs/` — Execution logs
- `tests/` — Unit, integration, e2e

### Function & Variable Naming
```python
# ❌ Cryptic or vague
def proc(x):
    ...

def validate_usr_data(d):
    ...

# ✅ Self-explanatory
def calculate_user_subscription_cost(subscription: Subscription) -> Decimal:
    ...

def extract_email_and_phone_from_user_input(raw_input: str) -> tuple[str, str]:
    ...
```

**Rule:** A function name should fully explain what it does without reading its body.

### Dependency Management with UV
**Rule:** Manage all dependencies using `uv` and update `pyproject.toml` accordingly.

### Core Engineering Principles

1. **Small, Focused Functions**
   - Max 20 lines per function
   - Each function does ONE thing
   - If naming it requires "and", split it

2. **Type Hints on Everything**
   ```python
   def get_user_by_id(user_id: int) -> User | None:
       ...
   ```

3. **Explicit Over Implicit**
   - No magic globals or module-level state
   - Dependency injection via `__init__` parameters
   - Constants in `core/config.py`, not scattered

4. **No Swallowing Errors**
   ```python
   # ❌ Bad
   try:
       result = risky_operation()
   except:
       pass
   
   # ✅ Good
   try:
       result = risky_operation()
   except TimeoutError:
       logger.warning("Operation timed out", exc_info=True)
       return None
   except DatabaseError as e:
       raise ServiceUnavailableError(f"DB unavailable: {e}") from e
   ```

5. **Data is Immutable by Default**
   ```python
   from dataclasses import dataclass
   
   @dataclass(frozen=True)
   class UserId:
       value: int
   ```

6. **Test-Driven: Red → Green → Refactor**
   - Write the test first (watch it fail)
   - Implement minimum to pass
   - Refactor with tests green
   - Never skip the refactor

7. **Spatial Reasoning First (Thinking in 3D)**
   - Do not rely on text-only planning or screenshot-only verification.
   - Combine semantic primitive planning with rendered views and deterministic 3D geometric evidence.
   - Never use ForgeCAD as the source of truth for geometry; use CadQuery and MeshLib.

8. **State & Durability Boundaries**
   - Temporal owns coarse stage state, retries, and approval gates.
   - Geometry Runtime trace owns detailed primitive execution artifacts. Do not bloat Temporal history with primitive calls.
   - Failed verification re-enters as a new planning attempt; no hidden state mutation.
   - **Storage model (PRD §09):** persistence = **artifact store** (one folder per run) + **Temporal history** (coarse stage state, heavy payloads by reference) + **trace JSON**. There is **no relational DB / ORM** in the MVP. The DB-flavoured items in the Production Checklist below (alembic migrations, testcontainers, ORM/SQL-injection, N+1 queries, connection pools) apply **only if** a relational store is later added — until then they are N/A.

9. **Trace Capture & Evals First**
   - Every attempt must produce an auditable trace (plan, geometry evidence, visual evidence, outcome labels).
   - **Failure Taxonomy**: Explicitly tag any workflow failure with one of the **6 canonical root causes (PRD §14)** before saving the trace, rather than returning a generic "Error": `primitive_gap`, `geometry_invalidity`, `visual_mismatch`, `translation_drift`, `verifier_miss`, `user_ambiguity`. The trace failure enum MUST carry all six — the "0 silent geometry failures" gate (PRD §11) depends on every failure having a category to land in.
   - Use traces for evaluation and regression testing first. Fine-tune models only after label trust is established.

10. **Clean Workspace**
    - Do not create new files unnecessarily; always prefer reusing or expanding existing modules.
    - Keep the codebase clean by actively deleting temporary testing, scratch, or debugging files after they have served their purpose.

---

# AGENTS.md — Codex Agent Operating Manual

> **Who I am:** A rookie AI developer, Python-first, vibe-coding toward production.
> **What you are:** My senior engineer you remember context across sessions,
> reason over a knowledge graph, push back on bad decisions, and keep production standards alive.

---

## 🧠 MEMORY & KNOWLEDGE ARCHITECTURE

This project uses a **two-layer memory system**. You must consult it at the start of every session and write back to it after every meaningful decision.

### Layer 1 — Episodic Memory: prefer mem0 for durable project context; use graphify for structural relationships when mem0 is unavailable; if neither is available, fall back to CLAUDE MEMORY and then git commit logs

mem0 stores the project’s durable context: architecture decisions, bug fixes, dependency choices, recurring patterns, and your stated preferences across sessions. Treat it as the living project logbook to consult before making changes and to update after meaningful decisions. When mem0 is not available, graphify and CLAUDE MEMORY provide the next-best sources for project continuity and historical context.

#### 1. Graphify (Structural Relationships)
Use the `/graphify` slash command to understand codebase structure and dependencies before making sweeping changes:
- `/graphify "Summary of main modules and their relationships"`
- `/graphify "Find any dead code or orphaned functions"`

#### 2. mem0 (Durable Context)
Use `mem0` to store and query architecture decisions, bug fixes, and preferences.

```python
# Setup & Load
from mem0 import Memory
memory = Memory.from_config({"llm": {"provider": "openai"}}) # Needs OPENAI_API_KEY or use Gemini key with openAI compatible "https://generativelanguage.googleapis.com/v1beta/openai/" end point of gemini and gemini api key.
ctx = memory.search(query="architecture decisions", user_id="project-slug")

# Write Back
memory.add(messages=[{"role": "user", "content": "[BUG_FIX] Fixed X because Y"}], user_id="project-slug")
```

**What to remember after each session:**
- Architecture decisions and the reason behind them
- Libraries chosen (and rejected) + why
- Bug root causes and how they were fixed
- Patterns established in this codebase
- My stated preferences for style, tooling, or approach
- TODOs that didn't get done this session

#### Querying Memory During Work
```python
# Before implementing a feature — check what was decided before

# Update a stale memory if something changed

# Remove a memory that's no longer true

```

---

## 🏁 SESSION STARTUP RITUAL — MANDATORY

Run these checks at the start of every session:
```bash
# 1. Git state & tests
git status --short
python -m pytest -q

# 2. Check TODOs
grep -r "TODO\|FIXME" src/
```
*Note: Also load episodic memory via `mem0` and run `/graphify` queries as needed before starting work.*


---

## 🧩 CORE OPERATING PRINCIPLES

### 1. Memory-Before-Action
Before implementing anything, search mem0 for:
- Prior decisions about this feature area
- Rejected approaches (and why)
- Known bugs related to this module
- My stated preferences

If a memory contradicts what I'm asking for now — **flag it**:
> *"According to session memory from last week, we decided against X because of Y. Do you want to revisit that?"*

### 2. Graph-Before-Refactor
Before touching any existing module or function:
1. Query the knowledge graph: who calls this? what does it import? what tests cover it?
2. Show me the impact radius
3. Only proceed if the change is understood end-to-end

### 3. Ask Before Acting
- Restate my request in your own words and confirm before implementing
- If a request is vague: ask **one focused question**, not five
- If my approach is suboptimal: say so directly with an alternative, don't silently comply

### 4. Small, Verified, Committed Steps
- One logical change per step
- Run `pytest -x` after every change — stop at first failure
- No step is "done" until the test is green and the graph is updated

---

## 📁 PROJECT ORIENTATION CHECKLIST

**Rule:** Always explore `pyproject.toml`, entry points, test layout, and existing patterns before modifying an unfamiliar repo.

---

## 🏗️ ARCHITECTURE & REUSE PRINCIPLES

### OSS-First — Never Build What Already Exists
Before writing any non-trivial utility:
1. Check if a PyPI package already does it: search `pypi.org`
2. Check if Django/FastAPI/SQLAlchemy already has this built in
3. Check if this project's `src/utils/` already has it: `grep -r "def <name>" src/`
4. Adapt an existing solution — only build from scratch as a last resort

### Geometry Agent Architecture — Enforce This
```
GAH-v2/
├── backend/       # Product API (FastAPI/uvicorn :8001): primitives_read/ skills_read/ (store.py+routes.py read-only doors) + designs/ (Temporal client)
├── temporal/      # Temporal job-manager: shared, activities, DesignWorkflow, worker
├── runtime/       # Pure stage logic (no Temporal): schema, planner, compile, trace
├── rlm/           # fast-rlm config + PULL HTTP-client tools (list/lookup primitives, read skill)
├── primitives/    # library.json — primitive specs (params + CadQuery templates)
├── tools/         # Leaf geometry tools: CadQuery (solids), mesh (inspect/repair), render, verify
├── skills/        # Reasoning guides served to the agent
├── evals/         # Eval corpus + suite built from run traces
├── artifacts/     # ONE FOLDER PER RUN: plan, CadQuery iterations, STEP/STL, renders, trace, feedback
├── logs/          # Execution logs
└── tests/         # Unit, integration, and e2e testing
```

**Rule:** The Geometry Runtime owns the detailed primitive loop. `CadQuery` is the geometry authority for solids, `MeshLib` for inspection. `ForgeCAD` receives editable output but is NOT the geometry authority. Temporal handles coarse stages, primitive-level detail stays in trace logs.

**ForgeCAD Handoff Contract** (source: github.com/KoStard/forgecad-public-kit)

*What it is:* browser-based, code-first parametric CAD. A model is a `.forge.js`
plain-JS file; the forge API (`box()`, `cylinder()`, `union()`, `difference()`,
`fillet()`, `.shell()`, `.onFace()`, `.extrude()`, ...) is injected as GLOBALS —
never `import` / `require`-destructure / shadow those names. Units = mm, angles =
degrees. Volumetric primitives are centered on XY with base at Z=0 (same
convention as our CadQuery solids).

*To display + edit in the UI, the emitted artifact must:*
1. Live in an initialized project folder (`forgecad.json` + `forgecad project init`);
   the long-lived `forgecad studio <path>` live-updates the 3D viewport on save and
   turns `Param.*` into interactive sliders.
2. RETURN a renderable — a single `Shape`/`Sketch`/`ShapeGroup`/`Assembly`/`SdfShape`,
   an array of those or named descriptors `{ name, tags?, shape|sketch|group, color? }`,
   or a metadata object whose keys each become a named group. Ops are immutable.
3. Declare parameters via `Param.number("Width", 90, { min, max, unit: "mm" })`
   — these become the UI sliders.

*`forgecad_emit` direction (NON-NEGOTIABLE):* emit `.forge.js` FROM the
PrimitivePlan, NOT by converting our STEP/STL. ForgeCAD's own reconstruct skill:
"imports are for measurement, rendering, and scoring only" — `Import.step()/mesh()`
of our solid is not an editable deliverable and kills parametric editability.
STEP stays the canonical artifact to validate against.

*Translation-drift gate (PRD §13) is a built-in command, not custom code:*
`forgecad compare 3d <our_canonical.step> <emitted.forge.js> --samples 5000 --json`
returns a 0-100 similarity score (surface + feature-edge F-score, volume IoU,
bounds/volume delta). Gate handoff on this score.

**Rule:** Additional folders may be created as the system scales, but all code MUST remain simple, modular, readable, and reusable.

### RLM (Recursive Language Model) Architecture
The core intelligence driving this system is based on **Recursive Language Models (RLMs)**. It operates as a task-agnostic inference paradigm that replaces standard JSON-based agents. 

The key components and principles of the RLM architecture in this project are:

1. **CodeAct-Style Execution (Replacing JSON Tools):** 
   RLMs completely abandon rigid JSON tool-calling schemas. Instead, the language model is dropped into a live Python REPL harness. It writes actual Python code to interact with its environment, manipulate context objects, and call sub-agents or tools directly as Python functions.
   
2. **Infinite Context via Recursion:** 
   Instead of shoving complex spatial reasoning or dense documentation into a single prompt, RLMs handle long contexts programmatically. The Root Agent can spawn isolated child agents (e.g., via `await llm_query(...)` inside the REPL) dedicated to specific sub-tasks like `repair_guidance` or `dimension_reasoning`. The sub-agent returns its result back to the root agent's code execution state, preventing context window overflow. (Top-level entry point from host Python is `fast_rlm.run(...)`; `llm_query` is the in-REPL recursion primitive — see `fast-rlm-reference`. There is no `rlm.completion`.)

3. **Pluggable REPL Sandboxes:** 
   Because the agent executes raw code, the "Brain" (LLM) is decoupled from the "Environment" (Sandbox). The system supports varying levels of isolation:
   - *LocalREPL / IPython:* Runs in-process on the host machine (fast, shares local virtual environment).
   - *Isolated / Cloud:* Uses Docker, E2B, Modal, or Prime sandboxes for completely secure, untrusted code execution.

> **Note on Tool Execution:** Because tools are invoked as standard Python functions within the REPL, they are subject to the capabilities of the chosen sandbox. If an isolated sandbox (like Pyodide/WebAssembly) is used, tools requiring host OS access must be bridged securely (e.g., via MCP servers).

----

## 🧪 TESTING STANDARDS

### Mandatory Testing Workflow (Red → Green → Commit)
```bash
# 1. Write the test first — watch it fail
python -m pytest tests/unit/test_new_feature.py -v    # should FAIL

# 2. Implement until green
python -m pytest tests/unit/test_new_feature.py -v    # should PASS

# 3. Run the full suite to confirm no regressions
python -m pytest -x --tb=short

# 4. Check coverage hasn't dropped
python -m pytest --cov=src --cov-report=term-missing --cov-fail-under=80
```

### Testing Hierarchy
| Type | Tool | Scope | Run When |
|------|------|-------|----------|
| Unit | `pytest` + `unittest.mock` | Single function | Every save |
| Integration | `pytest` + `httpx.AsyncClient` | API endpoints | Every commit |
| DB integration | `pytest` + `testcontainers` | Queries + migrations | Every schema change |
| E2E | `playwright` (Python) | Full user flows | Before every deploy |
| Contract | `schemathesis` | API schema conformance | Weekly / on schema change |

### Pytest Config
In `pyproject.toml`:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py", "*_test.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
asyncio_mode = "auto"
addopts = "-x --tb=short --strict-markers"

[tool.coverage.run]
source = ["src"]
omit = ["tests/*", "*/migrations/*", "*/__init__.py"]

[tool.coverage.report]
fail_under = 80
show_missing = true
```

### Test Naming Convention
```python
# Pattern: test_<unit>_<condition>_<expected_result>
def test_create_user_with_duplicate_email_raises_conflict_error():
    ...

def test_get_order_when_not_found_returns_none():
    ...

def test_process_payment_with_expired_card_returns_declined_status():
    ...
```

---

## 🚀 PRODUCTION READINESS CHECKLIST

Apply before every deploy. No exceptions.

### Security
- [ ] No secrets in code — all via `os.environ` + `.env` (never committed)
- [ ] `.env.example` committed with every variable documented
- [ ] Input validation: Pydantic models on all API inputs
- [ ] SQL injection impossible: ORM or parameterized queries only
- [ ] Auth enforced: every protected route tested with and without valid token
- [ ] `pip-audit` clean: `pip-audit --strict`
- [ ] Rate limiting on public endpoints

### Reliability
- [ ] All external HTTP calls have timeouts set: `httpx.get(url, timeout=10.0)`
- [ ] All DB calls have connection pool limits set
- [ ] Retry logic on transient failures (use `tenacity`)
- [ ] Every background task has error handling and dead-letter logging
- [ ] Health check endpoint: `GET /health` → `{"status": "ok", "version": "x.y.z"}`

### Observability
- [ ] Structured logging configured (`structlog` or `loguru` — never raw `print`)
- [ ] Request IDs propagated through every log line
- [ ] Error tracking connected (Sentry: `sentry_sdk.init(dsn=...)`)
- [ ] Key metrics exported (Prometheus or statsd)

### Performance
- [ ] No N+1 queries — all list endpoints use eager loading or batch fetch
- [ ] Slow query log enabled in dev (`echo=True` in SQLAlchemy for diagnosis)
- [ ] Heavy operations are async or queued (Celery, arq, or Dramatiq)
- [ ] Response pagination on all list endpoints

### Config
- [ ] `pyproject.toml` is source of truth for all tooling config
- [ ] `Dockerfile` present, builds clean, runs as non-root user
- [ ] `docker-compose.yml` for local dev (DB, cache, queue)
- [ ] `alembic` migrations present and `alembic upgrade head` tested on clean DB

---

## 🐍 PYTHON CODE QUALITY STANDARDS

### Non-Negotiable Rules
- **Type hints on every function signature** — no exceptions
- **Pydantic for all data boundaries** (API in/out, config, external service responses)
- **`ruff` for linting + formatting** (replaces flake8, isort, black — faster)
- **`mypy --strict` clean** before any PR

### Tooling & Patterns
**Rule:** Maintain `ruff` and `mypy --strict` configurations directly in `pyproject.toml`. Enforce explicit returns, DI, and immutable value objects.

---

## 🔄 GIT WORKFLOW

### Commit Message Format
```
type(scope): concise description in present tense

Types: feat | fix | refactor | test | docs | chore | perf | style

Examples:
feat(auth): add Google OAuth login flow
fix(payments): handle timeout when Stripe is unavailable
test(users): add integration tests for bulk user creation
chore(deps): upgrade SQLAlchemy to 2.0.35
```

### Before Every Commit — Run This
**Rule:** Always run `ruff check --fix`, `ruff format`, `mypy`, and `pytest` before committing.

### Never Commit
- `.env` files
- `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`
- Commented-out dead code
- Debug `print()` statements
- Hardcoded credentials or localhost URLs

---

## 📋 DOCUMENTATION STANDARDS

### Always Maintained
- **README.md**: Setup, env vars table, `make` commands, how to run tests, deploy instructions
- **`docs/decisions/`**: One markdown file per significant architecture decision (ADR format)
- **`.env.example`**: Every variable with description and example value — committed always
- **Docstrings**: On every public class and function — Google style.
- **ADRs**: Document significant architecture decisions in `docs/decisions/` using standard ADR format.

---




