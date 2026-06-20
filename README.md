# GAH-v2 — Geometry Agent Harness

A multi-agent CAD generation framework built on `fast-rlm`. A root agent coordinates the full pipeline from natural language → CadQuery code → STEP/STL export → mesh inspection → vision verification → trace.

## Features

- **Multi-phase CAD pipeline:** Intent extraction → primitive planning → code generation → execution → mesh QA → vision verification
- **Tool registry:** 11 tools registered in `tools/tools_registry.py` — skill reader, primitive lookup, CadQuery executor, mesh inspector, view renderer, geometry verifier, trace writer/loader
- **Skills system:** Reasoning guides in `skills/*.md` listed in `skills/SKILLS.md` and injected into task prompts. Agents load individual skills on demand via `read_skill(name)`
- **Primitives library:** 18 solid primitives defined in `primitives/library.json` with parameters, verification steps, and CadQuery templates
- **Subagent delegation:** Root agent spawns repair/refinement subagents with explicit tool passing

## Setup

### Python dependencies (uv)

```bash
uv sync
```

### CadQuery (requires conda)

CadQuery depends on compiled OpenCASCADE binaries not available via pip. Install via conda:

```bash
# Install Miniconda if needed
# https://docs.conda.io/en/latest/miniconda.html

conda create -n cad python=3.11 -y
conda install -n cad -c cadquery -c conda-forge cadquery=2.4.0 -y
```

`execute_cadquery` auto-detects the `~/miniconda3/envs/cad` environment.

## Environment Variables

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_gemini_api_key
```

## Models

Configured in `rlm/rlm_config.py`:

```python
config.primary_agent = "gemini-3.1-pro-preview"
config.sub_agent = "gemini-3.1-pro-preview"
```

## Project Structure

```
primitives/library.json   # 18 solid primitive schemas
skills/
  SKILLS.md               # Skill index injected into every task prompt
  *.md                    # Individual reasoning guides (loaded on demand)
  skills_loader.py        # Loads and injects SKILLS.md into task prompts
tools/
  tools_registry.py       # Central registry of all 11 agent tools
  execute_cadquery.py     # Runs CadQuery in conda subprocess
  inspect_mesh.py         # Mesh QA via MeshLib
  render_views.py         # Front/top/iso PNG renders via matplotlib
  verify_geometry.py      # Gemini vision judge
  write_trace.py          # Saves full run trace to outputs/traces/
  load_trace.py           # Loads saved traces
  read_skill.py           # Reads skill .md files
  primitive_lookup.py     # Queries primitives library
rlm/rlm_config.py         # fast-rlm config with Gemini adapter
outputs/                  # STEP, STL, PNG renders, trace JSON
```

## Running

```bash
uv run Task_test.py   # Example multi-agent task
uv run main.py                    # Basic entry point
```
