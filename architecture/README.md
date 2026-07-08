# GAH-v2 Architecture Diagrams

Presentation-ready architecture views of the GAH-v2 Geometry Agent Harness (milestone **M11**). Every diagram is authored in Mermaid and renders in GitHub, the VS Code Mermaid preview, and [mermaid.live](https://mermaid.live).

## Diagrams

| File | Purpose |
| :--- | :--- |
| [01_user_flow.md](01_user_flow.md) | End-to-end user journey (UI → intake → generate → post-design Q&A/edit) |
| [02_technical_architecture.md](02_technical_architecture.md) | Component/layer map (frontend, backend, runtime, tools, temporal, data) |
| [03_solution_architecture.md](03_solution_architecture.md) | Capability + value chain (Understand → Plan → Build → Validate → Verify → Self-correct → Deliver) |
| [04_enterprise_deployment.md](04_enterprise_deployment.md) | Docker container topology, ports, volumes, external API |
| [05_sequence_request_to_success.md](05_sequence_request_to_success.md) | Request → success timeline incl. intake + replan loop |
| [06_data_artifact_flow.md](06_data_artifact_flow.md) | Artifact transformations (prompt → plan → CadQuery → STL/STEP → renders → trace → Studio) |
| [07_state_machine.md](07_state_machine.md) | Session lifecycle + bounded inner/outer replan caps |
| [08_rlm_recursion.md](08_rlm_recursion.md) | CodeAct REPL, HTTP pull tools, depth-1 sub-agent recursion |

## Legend / Color key

Nodes are color-coded by architectural layer, consistently across all diagrams:

| Color | Layer | Meaning |
| :--- | :--- | :--- |
| 🟦 Blue | **UI** | Frontend, ForgeCAD Studio, browser-facing surfaces |
| 🟩 Green | **Backend** | FastAPI services, routes, runner, intake, read-only doors |
| 🟧 Orange | **Runtime** | Pure logic: planner, geometry loop, replan, compile, schema, trace |
| 🟪 Purple | **Tools** | Leaf wrappers: CadQuery execute, mesh inspect/repair, render, VLM |
| 🩷 Pink | **Temporal** | Durable workflow, activities, worker, Temporal server/UI/DB |
| ⬜ Grey | **External** | Google Gemini API and other external cloud services |
| 🟨 Yellow | **Data** | Artifact store (outputs/), primitives library, skills, volumes |

Shared `classDef` block used across the diagrams:

```
classDef ui       fill:#E3F2FD,stroke:#1976D2,color:#0D47A1;
classDef backend  fill:#E8F5E9,stroke:#388E3C,color:#1B5E20;
classDef runtime  fill:#FFF3E0,stroke:#F57C00,color:#E65100;
classDef tools    fill:#F3E5F5,stroke:#8E24AA,color:#4A148C;
classDef temporal fill:#FCE4EC,stroke:#C2185B,color:#880E4D;
classDef external fill:#ECEFF1,stroke:#546E7A,color:#263238;
classDef data     fill:#FFFDE7,stroke:#F9A825,color:#F57F17;
```
