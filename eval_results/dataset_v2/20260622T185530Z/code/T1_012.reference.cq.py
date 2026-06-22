import cadquery as cq
result = cq.Workplane('XY').polygon(3, 30).extrude(50)