# Solution Architecture

Capability and value chain: how a natural-language prompt flows through the seven solution capabilities (Understand → Plan → Build → Validate → Verify → Self-correct → Deliver) to produce editable, auditable CAD output.

```mermaid
flowchart TD
    subgraph IN[Input]
        U["Natural-language prompt<br/>+ optional reference images"]
    end
    subgraph CAP[Solution Capabilities]
        C1["1 Understand<br/>Conversational intake clarifies intent"]
        C2["2 Plan<br/>RLM agent → structured PrimitivePlan"]
        C3["3 Build<br/>Deterministic CadQuery → solid geometry"]
        C4["4 Validate<br/>MeshLib watertight + auto-repair"]
        C5["5 Verify<br/>Vision LLM judges renders vs intent"]
        C6["6 Self-correct<br/>Bounded replan loop on any failure"]
        C7["7 Deliver<br/>Editable model in ForgeCAD Studio"]
    end
    subgraph OUT[Output + Value]
        O1["STEP · STL · renders"]
        O2["Editable parametric model"]
        O3["Auditable trace + failure taxonomy"]
    end
    U --> C1 --> C2 --> C3 --> C4 --> C5 --> C7
    C4 -. fail .-> C6
    C5 -. fail .-> C6
    C6 --> C2
    C7 --> O1 & O2
    C6 --> O3
    class U ui
    class C1,C2,C6 backend
    class C3,C4 runtime
    class C5 tools
    class C7 temporal
    class O1,O2,O3 data

    classDef ui       fill:#E3F2FD,stroke:#1976D2,color:#0D47A1;
    classDef backend  fill:#E8F5E9,stroke:#388E3C,color:#1B5E20;
    classDef runtime  fill:#FFF3E0,stroke:#F57C00,color:#E65100;
    classDef tools    fill:#F3E5F5,stroke:#8E24AA,color:#4A148C;
    classDef temporal fill:#FCE4EC,stroke:#C2185B,color:#880E4D;
    classDef external fill:#ECEFF1,stroke:#546E7A,color:#263238;
    classDef data     fill:#FFFDE7,stroke:#F9A825,color:#F57F17;
```
