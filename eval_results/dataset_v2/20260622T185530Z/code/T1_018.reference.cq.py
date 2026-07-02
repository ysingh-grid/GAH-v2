import cadquery as cq
result = cq.Workplane('XY').polygon(5, 25).extrude(40)