import cadquery as cq
result = (
    cq.Workplane('XY')
    .circle(30)
    .workplane(offset=35)
    .circle(20)
    .loft()
)