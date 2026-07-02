import cadquery as cq
result = (
    cq.Workplane('XY')
    .circle(25)
    .circle(12.5)
    .extrude(4)
)