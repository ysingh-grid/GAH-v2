# Data / Artifact Flow

How data transforms through the pipeline: prompt → intake facts → PrimitivePlan → CadQuery script → STL/STEP → (repair) → renders → verdict → trace, with the best STL copied to the ForgeCAD Studio workspace on success.

```mermaid
flowchart LR
    P0["Prompt + images"]:::ui
    F0["Intake facts (markdown)"]:::backend
    J0["PrimitivePlan JSON<br/>(schema.py)"]:::runtime
    C0["CadQuery script .py"]:::runtime
    S0["solid.stl + solid.step<br/>+ volume/bbox metrics"]:::data
    R0["solid_repaired.stl<br/>(if not watertight)"]:::data
    V0["threeview.png"]:::tools
    D0["Verdict JSON"]:::tools
    T0["trace.json<br/>plan+code+metrics+outcome+category"]:::data
    W0["artifacts/forgecad/solid.stl<br/>+ main.forge.js"]:::ui
    P0 --> F0 --> J0 --> C0 --> S0
    S0 -->|inspect fail| R0
    S0 --> V0
    R0 --> V0
    V0 --> D0
    J0 & C0 & S0 & V0 & D0 --> T0
    S0 -->|on success| W0
    R0 -->|preferred if exists| W0

    classDef ui       fill:#E3F2FD,stroke:#1976D2,color:#0D47A1;
    classDef backend  fill:#E8F5E9,stroke:#388E3C,color:#1B5E20;
    classDef runtime  fill:#FFF3E0,stroke:#F57C00,color:#E65100;
    classDef tools    fill:#F3E5F5,stroke:#8E24AA,color:#4A148C;
    classDef temporal fill:#FCE4EC,stroke:#C2185B,color:#880E4D;
    classDef external fill:#ECEFF1,stroke:#546E7A,color:#263238;
    classDef data     fill:#FFFDE7,stroke:#F9A825,color:#F57F17;
```
