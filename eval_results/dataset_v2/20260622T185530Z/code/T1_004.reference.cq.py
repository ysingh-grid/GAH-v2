import cadquery as cq
result = cq.Workplane('XY').circle(15).workplane(offset=45).circle(0.01).loft()