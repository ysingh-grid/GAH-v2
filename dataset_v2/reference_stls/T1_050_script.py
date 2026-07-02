import cadquery as cq
result = (
    cq.Workplane('XY')
    .box(40, 20, 60)
    .edges('|Z')
    .fillet(4)
)