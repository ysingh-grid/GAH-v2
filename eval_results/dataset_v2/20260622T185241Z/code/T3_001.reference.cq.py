import cadquery as cq
result = (
    cq.Workplane('XY')
    .rect(60, 40)
    .extrude(30.0)
    .edges('|Z')
    .fillet(5.0)
    .faces('>Z')
    .shell(-2.0)
)