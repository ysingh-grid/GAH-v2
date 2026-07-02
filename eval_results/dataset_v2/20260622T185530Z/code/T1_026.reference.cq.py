import cadquery as cq
result = (
    cq.Workplane('XY')
    .circle(15)
    .circle(12)
    .extrude(80)
)