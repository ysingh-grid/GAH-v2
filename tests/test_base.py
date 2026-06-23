import cadquery as cq
import meshlib.mrmeshpy as mm
import trimesh
import tempfile
import os

from cad_kernel.kernel import build_plan

plan = {"title":"Ergonomic Office Chair","assembly_kind":"assembly","overall_dimensions":{"width":650,"length":650,"height":1200},"primitives_sequence":[{"sequence_id":1,"name":"base_hub","primitive_type":"cylinder","parameters":{"radius":50,"height":80},"operation":"new","part":"base"},{"sequence_id":2,"name":"leg_1","primitive_type":"box","parameters":{"width":300,"length":50,"height":40},"operation":"join","position":[175,0,20],"part":"base"},{"sequence_id":3,"name":"leg_2","primitive_type":"box","parameters":{"width":300,"length":50,"height":40},"operation":"join","position":[175,0,20],"rotation":[0,0,72],"part":"base"},{"sequence_id":4,"name":"leg_3","primitive_type":"box","parameters":{"width":300,"length":50,"height":40},"operation":"join","position":[175,0,20],"rotation":[0,0,144],"part":"base"},{"sequence_id":5,"name":"leg_4","primitive_type":"box","parameters":{"width":300,"length":50,"height":40},"operation":"join","position":[175,0,20],"rotation":[0,0,216],"part":"base"},{"sequence_id":6,"name":"leg_5","primitive_type":"box","parameters":{"width":300,"length":50,"height":40},"operation":"join","position":[175,0,20],"rotation":[0,0,288],"part":"base"}],"contains_freeform":False}

res = build_plan(plan)
solid = list(res["solid"].vals())[0].val() if hasattr(list(res["solid"].vals())[0], "val") else list(res["solid"].vals())[0]

f = tempfile.mktemp(suffix=".stl")
cq.exporters.export(solid, f)

mesh = trimesh.load(f)
os.remove(f)

print(f"Trimesh components: {mesh.body_count}")
for i, comp in enumerate(mesh.split()):
    print(f"Component {i}: bounds={comp.bounds}, volume={comp.volume}")

