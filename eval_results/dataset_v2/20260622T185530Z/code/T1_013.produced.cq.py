import cadquery as cq


def _place(solid, position, orientation):
    """Rotate about the origin (X, then Y, then Z degrees) then translate."""
    rx, ry, rz = orientation
    solid = (
        solid.rotate((0, 0, 0), (1, 0, 0), rx)
        .rotate((0, 0, 0), (0, 1, 0), ry)
        .rotate((0, 0, 0), (0, 0, 1), rz)
    )
    return solid.translate(position)


def _polar(solid, count, axis, angle_deg):
    """Union `count` copies orbited about `axis` (through origin), evenly spread."""
    out = None
    for k in range(count):
        copy = solid.rotate((0, 0, 0), axis, k * (angle_deg / count))
        out = copy if out is None else out.union(copy)
    return out


def _linear(solid, count, spacing):
    """Union `count` copies, each offset from the previous by `spacing`."""
    sx, sy, sz = spacing
    out = None
    for k in range(count):
        copy = solid.translate((sx * k, sy * k, sz * k))
        out = copy if out is None else out.union(copy)
    return out

# part: stadium_part (units: mm)
# step 'base_box' — base box
s0 = cq.Workplane("XY").box(42, 20, 8)
s0 = _place(s0, (0.0, 0.0, 4.0), (0.0, 0.0, 0.0))
result = s0

# step 'left_cylinder' — union cylinder
s1 = cq.Workplane("XY").cylinder(8, 10)
s1 = _place(s1, (-20.0, 0.0, 4.0), (0.0, 0.0, 0.0))
result = result.union(s1)

# step 'right_cylinder' — union cylinder
s2 = cq.Workplane("XY").cylinder(8, 10)
s2 = _place(s2, (20.0, 0.0, 4.0), (0.0, 0.0, 0.0))
result = result.union(s2)
