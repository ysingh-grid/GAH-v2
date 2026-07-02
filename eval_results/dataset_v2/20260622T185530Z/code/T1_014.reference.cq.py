import cadquery as cq
result = cq.Workplane('XY').polygon(8, 40).extrude(15)