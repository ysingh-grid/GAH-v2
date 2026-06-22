import cadquery as cq
result = cq.Workplane('XY').circle(20).workplane(offset=30).circle(10).loft()