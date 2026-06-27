"""
_custom_runner.py — isolated, standalone runner for an LLM-authored code_sketch.

Invoked as a subprocess:  python _custom_runner.py <code_file> <out_brep>
Execs the code (which must bind `result`), then writes the resulting solid as a
true BREP (not a tessellated STL), so the main process can re-import it and still
perform exact boolean operations against primitives.

Isolation: a separate OS process with a hard timeout enforced by the caller — bad
or looping generated code cannot hang or corrupt the planning process. Using a
standalone script (not multiprocessing 'spawn') makes this robust regardless of
how the parent was launched (CLI, REPL, notebook, embedded).
"""
import math
import sys

import cadquery as cq
from OCP.BRepTools import BRepTools


def main():
    code_file, out_brep = sys.argv[1], sys.argv[2]
    context_file = sys.argv[3] if len(sys.argv) > 3 else None
    
    with open(code_file, "r", encoding="utf-8") as f:
        code = f.read()
        
    ns = {"cq": cq, "math": math}
    
    if context_file:
        import json
        with open(context_file, "r", encoding="utf-8") as f:
            ctx = json.load(f)
        from OCP.BRep import BRep_Builder
        from OCP.TopoDS import TopoDS_Shape
        for name, path in ctx.items():
            try:
                shape = TopoDS_Shape()
                BRepTools.Read_s(shape, path, BRep_Builder())
                ns[name] = cq.Workplane("XY").add(cq.Shape.cast(shape))
            except Exception:
                pass

    exec(code, ns)
    obj = ns.get("result")
    if obj is None:
        # The model often binds a named variable (base/seat/backrest) instead of `result`.
        # Be forgiving: use the LAST-assigned CadQuery object in the namespace.
        for key in reversed(list(ns.keys())):
            if key in ("cq", "math") or key.startswith("__"):
                continue
            val = ns[key]
            if isinstance(val, (cq.Workplane, cq.Shape, cq.Solid, cq.Compound)):
                obj = val
                break
    if obj is None:
        sys.stderr.write("custom code_sketch did not produce a CadQuery solid "
                         "(bind it to `result` or any variable)")
        sys.exit(2)
    solid = obj.val() if hasattr(obj, "val") else obj
    BRepTools.Write_s(solid.wrapped, out_brep)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        sys.stderr.write(f"{type(e).__name__}: {e}")
        sys.exit(1)
