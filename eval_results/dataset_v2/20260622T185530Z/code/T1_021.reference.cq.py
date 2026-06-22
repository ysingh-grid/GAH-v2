import cadquery as cq
result = (
    cq.Workplane('XY')
    .rect(60, 30)
    .workplane(offset=25)
    .rect(60, 0.01)
    .loft()
)