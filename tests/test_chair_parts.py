import cadquery as cq
import meshlib.mrmeshpy as mm
import tempfile
import os
from cad_kernel.kernel import build_plan

plan = {"title":"Ergonomic Office Chair","assembly_kind":"assembly","overall_dimensions":{"width":650,"length":650,"height":1200},"primitives_sequence":[{"sequence_id":1,"name":"base_hub","primitive_type":"cylinder","parameters":{"radius":50,"height":80},"operation":"new","part":"base","rationale":"Central hub for the 5-star base, providing a strong mounting point for the legs and the gas lift."},{"sequence_id":2,"name":"leg_1","primitive_type":"box","parameters":{"width":300,"length":50,"height":40},"operation":"join","position":[175,0,20],"part":"base","rationale":"First of five legs for the stable base, designed to distribute weight evenly."},{"sequence_id":3,"name":"leg_2","primitive_type":"box","parameters":{"width":300,"length":50,"height":40},"operation":"join","position":[175,0,20],"rotation":[0,0,72],"part":"base","rationale":"Second of five legs for the stable base."},{"sequence_id":4,"name":"leg_3","primitive_type":"box","parameters":{"width":300,"length":50,"height":40},"operation":"join","position":[175,0,20],"rotation":[0,0,144],"part":"base","rationale":"Third of five legs for the stable base."},{"sequence_id":5,"name":"leg_4","primitive_type":"box","parameters":{"width":300,"length":50,"height":40},"operation":"join","position":[175,0,20],"rotation":[0,0,216],"part":"base","rationale":"Fourth of five legs for the stable base."},{"sequence_id":6,"name":"leg_5","primitive_type":"box","parameters":{"width":300,"length":50,"height":40},"operation":"join","position":[175,0,20],"rotation":[0,0,288],"part":"base","rationale":"Fifth of five legs for the stable base."},{"sequence_id":7,"name":"gas_lift","primitive_type":"cylinder","parameters":{"radius":25,"height":350},"operation":"new","attach":{"to":"base_hub","at":"top","my_anchor":"bottom"},"part":"gas_lift","rationale":"The gas lift allows for seat height adjustment, a key ergonomic feature."},{"sequence_id":8,"name":"seat_base","primitive_type":"box","parameters":{"width":450,"length":450,"height":50},"operation":"new","attach":{"to":"gas_lift","at":"top","my_anchor":"bottom"},"part":"seat","rationale":"The main seat structure, providing a platform for the cushion and user."},{"sequence_id":9,"name":"backrest","primitive_type":"custom","parameters":{"shape_description":"A rectangular cushion with a slight indentation on the front face for comfort.","cadquery_operations":["Workplane.box","Workplane.faces","Workplane.workplane","Workplane.rect","Workplane.cutBlind"],"code_sketch":"result = cq.Workplane('XY').box(500, 50, 600).faces('>Y').workplane().rect(480, 580).cutBlind(-20)","declared_dimensions":{"width":500,"thickness":50,"height":600,"indent_depth":20}},"operation":"new","attach":{"to":"seat_base","at":"back","my_anchor":"bottom"},"part":"backrest","rationale":"Provides ergonomic support to the user's back, crucial for comfort during long periods of sitting."},{"sequence_id":10,"name":"left_armrest","primitive_type":"custom","parameters":{"shape_description":"A curved armrest with a flat top surface.","cadquery_operations":["Workplane.line","Workplane.threePointArc","Workplane.extrude"],"code_sketch":"result = cq.Workplane('XY').line(0, 200).threePointArc((50, 250), (0, 300)).close().extrude(40).translate((-250, -225, 0))","declared_dimensions":{"length":300,"width":50}},"operation":"new","attach":{"to":"seat_base","at":"left","my_anchor":"bottom"},"part":"armrests","rationale":"Provides support for the user's arms, reducing strain on the shoulders and neck."},{"sequence_id":11,"name":"right_armrest","primitive_type":"custom","parameters":{"shape_description":"A curved armrest with a flat top surface, mirrored from the left armrest.","cadquery_operations":["Workplane.line","Workplane.threePointArc","Workplane.extrude"],"code_sketch":"result = cq.Workplane('XY').line(0, 200).threePointArc((50, 250), (0, 300)).close().extrude(40).translate((200, -225, 0))","declared_dimensions":{"length":300,"width":50}},"operation":"new","attach":{"to":"seat_base","at":"right","my_anchor":"bottom"},"part":"armrests","rationale":"Provides support for the user's arms, reducing strain on the shoulders and neck."}],"contains_freeform":True}

res = build_plan(plan)
solid = res["solid"]

# We have a compound. Let's analyze each solid in the compound.
shapes = []
for v in solid.vals():
    shapes.append(v.val() if hasattr(v, "val") else v)

print(f"Total solids in compound: {len(shapes)}")

for i, s in enumerate(shapes):
    f = tempfile.mktemp(suffix=".stl")
    cq.exporters.export(s, f)
    mesh = mm.loadMesh(f)
    os.remove(f)
    
    comps = int(mm.MeshComponents.getNumComponents(mesh))
    intersections = int(mm.findSelfCollidingTriangles(mm.MeshPart(mesh)).size())
    print(f"Solid {i}: Volume={mesh.volume():.2f}, Components={comps}, Intersections={intersections}")

