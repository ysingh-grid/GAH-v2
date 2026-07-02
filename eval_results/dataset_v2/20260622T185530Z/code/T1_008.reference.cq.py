import cadquery as cq
result = cq.Workplane('XY').sphere(25).split(keepTop=True)