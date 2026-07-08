# RLM Recursion Architecture (CodeAct)

How the planner works: a Gemini Pro root agent runs a CodeAct Python REPL, calls HTTP pull tools for primitives and skills, optionally spawns a depth-1 Gemini Flash sub-agent, and emits a validated PrimitivePlan.

```mermaid
flowchart TD
    SYS["Planner entry<br/>fast_rlm.run(...)"]:::backend
    subgraph REPL[Root Agent REPL - Gemini Pro]
        CODE["Writes Python (CodeAct)<br/>max 20 steps · truncate 12k"]
        T1["list_primitives()"]
        T2["lookup_primitive(name)"]
        T3["read_skill(name)"]
        SUB["llm_query(...) → sub-agent<br/>max_depth = 1"]
        FIN["plan_ready → PrimitivePlan"]
    end
    subgraph SA[Sub-agent - Gemini Flash]
        LEAF["Isolated leaf reasoning<br/>returns result to REPL state"]
    end
    subgraph SRC[Backend pull tools - HTTP]
        LIBAPI["/internal/primitives/*"]
        SKAPI["/internal/skills/*"]
    end
    SYS --> CODE
    CODE --> T1 & T2 & T3
    CODE --> SUB --> LEAF --> CODE
    T1 & T2 --> LIBAPI
    T3 --> SKAPI
    CODE --> FIN
    FIN --> OUTP["Validated plan → geometry loop"]:::runtime
    class T1,T2,T3,SUB,FIN,CODE runtime
    class LEAF external
    class LIBAPI,SKAPI backend

    classDef ui       fill:#E3F2FD,stroke:#1976D2,color:#0D47A1;
    classDef backend  fill:#E8F5E9,stroke:#388E3C,color:#1B5E20;
    classDef runtime  fill:#FFF3E0,stroke:#F57C00,color:#E65100;
    classDef tools    fill:#F3E5F5,stroke:#8E24AA,color:#4A148C;
    classDef temporal fill:#FCE4EC,stroke:#C2185B,color:#880E4D;
    classDef external fill:#ECEFF1,stroke:#546E7A,color:#263238;
    classDef data     fill:#FFFDE7,stroke:#F9A825,color:#F57F17;
```
