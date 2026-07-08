# Enterprise / Deployment Architecture

Docker Compose container topology (milestone M11): backend, worker, Temporal server + Postgres + Web UI, and ForgeCAD Studio — with ports, host volumes, injected secrets, and the external Gemini API.

```mermaid
flowchart TB
    subgraph HOST[Developer / Host machine]
        ENV[".env → GEMINI_API_KEY"]
        VOL[("Volumes<br/>./outputs · ./logs<br/>./artifacts")]
    end
    subgraph DOCKER[Docker Compose]
        BE["gah-backend<br/>:8001 FastAPI + UI"]
        WK["gah-worker<br/>Temporal activities"]
        TS["gah-temporal :7233"]
        TDB[("gah-temporal-db<br/>Postgres")]
        TUI["gah-temporal-ui :8088"]
        FCS["gah-forgecad :4000<br/>Studio"]
    end
    subgraph CLOUD[External Cloud]
        GEM["Google Gemini API"]
    end
    USER([Browser]) -->|:8001/ui| BE
    USER -->|:4000| FCS
    USER -->|:8088| TUI
    BE -->|gRPC :7233| TS
    WK -->|gRPC :7233| TS
    TS --> TDB
    TUI --> TS
    BE & WK -->|HTTPS| GEM
    ENV -.injected.-> BE & WK
    BE & WK -.read/write.-> VOL
    FCS -.reads.-> VOL
    class USER ui
    class BE,WK backend
    class TS,TDB,TUI temporal
    class FCS ui
    class GEM external
    class ENV,VOL data

    classDef ui       fill:#E3F2FD,stroke:#1976D2,color:#0D47A1;
    classDef backend  fill:#E8F5E9,stroke:#388E3C,color:#1B5E20;
    classDef runtime  fill:#FFF3E0,stroke:#F57C00,color:#E65100;
    classDef tools    fill:#F3E5F5,stroke:#8E24AA,color:#4A148C;
    classDef temporal fill:#FCE4EC,stroke:#C2185B,color:#880E4D;
    classDef external fill:#ECEFF1,stroke:#546E7A,color:#263238;
    classDef data     fill:#FFFDE7,stroke:#F9A825,color:#F57F17;
```
