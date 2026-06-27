#!/usr/bin/env bash
# Optional repo tidy-up — run from the repo root:  bash reorg_repo.sh
#
# Moves loose ROOT docs + dev scripts into folders. It deliberately does NOT touch the working code
# packages (cad_kernel/ schemas/ tools/ skills/ tests/ cadquery_kb_pack/ meshlib_kb_pack/) or the
# imported root modules (orchestrator.py ui_server.py plan_store.py trace_view.py run.yaml
# requirements.txt), because moving those breaks imports / MCP launch paths / run.yaml.
set -euo pipefail

mkdir -p docs scripts

# Historical dev notes -> docs/  (after moving, delete their lines from .gitignore to publish them)
for f in CHANGES_phase0.md CHANGES_phase1.md CHANGES_phase1b.md CHANGES_phase2.md CHANGES_phase3.md \
         CHANGES_phase4.md CHANGES_phase5.md CHANGES_phase6.md CHANGES_v4.md CHANGES_v5.md \
         FIXES.md DIAGNOSIS_AND_FIX.md PLANNING_UPGRADE.md PHASE2_BUILD_VERIFY.md explanation.md \
         AI_Harness_ForgeCAD_Magazine.html; do
  [ -f "$f" ] && mv -v "$f" docs/ || true
done
[ -f "Copy of Design Process.pdf" ] && mv -v "Copy of Design Process.pdf" docs/ || true

# Standalone dev utilities -> scripts/  (NOT trace_view.py / plan_store.py — those are imported)
for f in split_stl.py parse_log.py test_fix.py; do
  [ -f "$f" ] && mv -v "$f" scripts/ || true
done

# Scratch outputs -> delete (regenerated every run; already gitignored)
rm -fv current_plan.txt latest_log_chunk.txt office_chair_plan.txt test_gear.stl

echo "Done. README.md + fix.md stay at root as the canonical docs."
