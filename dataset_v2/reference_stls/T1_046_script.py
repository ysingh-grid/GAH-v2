import cadquery as cq
result = (
    cq.Workplane('XY')
    .box(20, 20, 20)
    .edges()
    .fillet(3)
)