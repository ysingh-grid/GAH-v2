import cadquery as cq
result = (
    cq.Workplane('XY')
    .box(30, 30, 30)
    .edges()
    .chamfer(2)
)