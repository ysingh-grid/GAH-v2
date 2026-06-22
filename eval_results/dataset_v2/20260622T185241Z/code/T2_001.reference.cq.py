import cadquery as cq
result = (
    cq.Workplane('XY')
    .circle(10.0)
    .circle(5.25)
    .extrude(2.0)
)