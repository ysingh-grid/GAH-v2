import cadquery as cq
result = cq.Workplane('XY').slot2D(60, 20).extrude(8)