# Available Skills

Use `read_skill(name)` to load any skill file.

**Core skills** (like `playbook` and `primitive_planning`) are pre-loaded in `context['preloaded_skills']` on startup. Read them directly. Do NOT call `read_skill()` for these core guides!

- `playbook`   ← preloaded
- `intent_extraction`
- `part_decomposition`
- `primitive_planning` ← preloaded
- `dimension_reasoning`
- `verification_planning`