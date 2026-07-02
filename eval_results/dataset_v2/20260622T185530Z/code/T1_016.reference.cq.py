import cadquery as cq
result = cq.Workplane('XY').ellipse(20, 10).extrude(25)