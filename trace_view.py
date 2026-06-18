import json
import sys
from collections import defaultdict


def _load(path):
    return [json.loads(l) for l in open(path) if l.strip()]


def render_trace(path):
    events = _load(path)
    runs, order, children = {}, [], defaultdict(list)
    for e in events:
        rid = e.get("run_id")
        if rid and rid not in runs:
            runs[rid] = {"depth": e.get("depth", 0),
                         "parent": e.get("parent_run_id"), "events": []}
            order.append(rid)
        if rid:
            runs[rid]["events"].append(e)
    for rid, r in runs.items():
        children[r["parent"]].append(rid)

    total_tok = sum((e.get("usage") or {}).get("total_tokens", 0) or 0 for e in events)
    total_cost = sum((e.get("usage") or {}).get("cost", 0) or 0 for e in events)

    def walk(rid, indent):
        r = runs[rid]
        pad = "  " * indent
        tag = "ROOT" if r["depth"] == 0 else "subagent"
        print(f"{pad}\u25cf {tag}  depth={r['depth']}  id=\u2026{rid[-6:]}")
        for e in r["events"]:
            et = e.get("event_type")
            if et == "code_generated":
                first = ((e.get("code") or "").strip().splitlines() or [""])[0]
                print(f"{pad}  \u00b7 step {e.get('step')}: {first[:78]}")
            elif et == "execution_result":
                for ln in (e.get("output") or "").splitlines():
                    if ln.startswith("[[TOOL]]"):
                        print(f"{pad}    \U0001f527 {ln[8:].strip()}")
                if e.get("hasError"):
                    print(f"{pad}    \u26a0 error in step {e.get('step')}")
            elif et == "final_result":
                print(f"{pad}  \u2713 FINAL")
        for c in children.get(rid, []):
            walk(c, indent + 1)

    for rid in order:
        if runs[rid]["parent"] is None:
            walk(rid, 0)
    print(f"\nTOTAL  tokens={total_tok:,}  cost=${total_cost:.4f}")


if __name__ == "__main__":
    render_trace(sys.argv[1])
