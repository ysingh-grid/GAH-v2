# Technical / Component Architecture

Component and layer map of GAH-v2 showing the frontend, backend services, pure runtime, leaf tools, the optional Temporal layer, external Gemini API, and the artifact data store — including the in-process vs. Temporal execution fork.

```mermaid
flowchart LR
    subgraph CLIENT[Client]
        UI["Frontend /ui<br/>index.html · app.js"]
        FC["ForgeCAD Studio<br/>:4000 iframe"]
    end
    subgraph API[Backend FastAPI :8001]
        APP["app.py<br/>/health · /config · CORS"]
        WS["designs/routes.py<br/>WS /designs/id/chat"]
        RUN["designs/runner.py<br/>run_chat_turn"]
        INT["designs/intake.py"]
        PR["primitives_read"]
        SK["skills_read"]
        KB["kb_read · web_search"]
    end
    subgraph RT[Runtime - pure logic]
        PLAN["planner.py (fast-rlm)"]
        LOOP["loop.py geometry loop"]
        REPLAN["replan.py"]
        COMPILE["compile_cadquery.py"]
        SCHEMA["schema.py PrimitivePlan"]
        TRACE["trace.py taxonomy"]
    end
    subgraph TOOLS[Tools - leaf wrappers]
        EXEC["execute_cadquery"]
        MESH["inspect · repair mesh"]
        REND["render_views"]
        VLM["vlm_judge · vlm_intake"]
    end
    subgraph TEMP[Temporal - optional]
        WF["workflow.py DesignWorkflow"]
        ACT["activities.py x8"]
        WORK["worker.py"]
    end
    subgraph EXT[External]
        GEM["Google Gemini API"]
    end
    subgraph DATA[Data - artifact store]
        OUT["outputs/run_id/*"]
        LIB["primitives/library.json"]
        SKF["skills/*.md"]
    end
    UI -->|WebSocket| WS --> RUN
    RUN --> INT --> VLM
    RUN --> PLAN
    RUN -->|TEMPORAL_HOST set| WF
    RUN -->|else in-process| LOOP
    PLAN -->|HTTP pull tools| PR & SK
    WF --> ACT --> LOOP
    WORK -.hosts.-> ACT
    LOOP --> COMPILE --> EXEC --> MESH --> REND --> VLM
    LOOP --> REPLAN --> PLAN
    PLAN & INT & VLM --> GEM
    COMPILE --> SCHEMA
    LOOP --> TRACE --> OUT
    REND --> OUT
    RUN -->|copy STL| FC
    PR --> LIB
    SK --> SKF
    class UI,FC ui
    class APP,WS,RUN,INT,PR,SK,KB backend
    class PLAN,LOOP,REPLAN,COMPILE,SCHEMA,TRACE runtime
    class EXEC,MESH,REND,VLM tools
    class WF,ACT,WORK temporal
    class GEM external
    class OUT,LIB,SKF data

    classDef ui       fill:#E3F2FD,stroke:#1976D2,color:#0D47A1;
    classDef backend  fill:#E8F5E9,stroke:#388E3C,color:#1B5E20;
    classDef runtime  fill:#FFF3E0,stroke:#F57C00,color:#E65100;
    classDef tools    fill:#F3E5F5,stroke:#8E24AA,color:#4A148C;
    classDef temporal fill:#FCE4EC,stroke:#C2185B,color:#880E4D;
    classDef external fill:#ECEFF1,stroke:#546E7A,color:#263238;
    classDef data     fill:#FFFDE7,stroke:#F9A825,color:#F57F17;
```
