import cadquery as cq
result = (
    cq.Workplane('XY')
    .box(50, 25, 15)
    .edges('|Z')
    .fillet(3)
)