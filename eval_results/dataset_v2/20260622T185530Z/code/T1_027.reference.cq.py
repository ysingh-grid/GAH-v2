import cadquery as cq
result = (
    cq.Workplane('XY')
    .box(70, 40, 25)
    .edges()
    .fillet(5)
)