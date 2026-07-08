# State Machine: Session + Replan Loop

Design-session lifecycle and the bounded repair loop: the inner cap governs geometry-stage failures (compile/execute/repair) and the outer cap governs visual mismatches, with post-design question and edit transitions.

```mermaid
stateDiagram-v2
    [*] --> New: POST /designs
    New --> Intake: first message
    Intake --> Intake: ask_user / answer
    Intake --> Generating: facts ready → planner
    state Generating {
        [*] --> Compile
        Compile --> Execute
        Execute --> Inspect
        Inspect --> Repair: not watertight
        Inspect --> Render: watertight
        Repair --> Render
        Render --> Verify
        Verify --> [*]: passed
        Verify --> Replan: visual_mismatch (outer cap 2)
        Compile --> Replan: geometry fail (inner cap 5)
        Execute --> Replan
        Repair --> Replan
        Replan --> Compile
    }
    Generating --> Done: verified
    Generating --> Failed: caps exhausted / replan_error
    Done --> Question: post-design ask
    Question --> Done
    Done --> EditIntake: post-design edit
    Failed --> EditIntake
    EditIntake --> Generating: edit clarified
    Done --> [*]
    Failed --> [*]
```
