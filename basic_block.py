import cadquery as cq

def create_basic_block():
    width = 60
    depth = 40
    height = 20
    chamfer_size = 2

    basic_block = (
        cq.Workplane("XY")
        .box(width, depth, height)
        .faces(">Z")
        .edges()
        .chamfer(chamfer_size)
    )

    return basic_block

basic_block = create_basic_block()
