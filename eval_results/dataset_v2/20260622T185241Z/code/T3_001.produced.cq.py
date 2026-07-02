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

# part: open_top_rounded_container (units: mm)
# step 'outer_box_base' — base box
s0 = cq.Workplane("XY").box(60, 30, 30)
s0 = _place(s0, (0.0, 0.0, 15.0), (0.0, 0.0, 0.0))
result = s0

# step 'outer_box_union' — union box
s1 = cq.Workplane("XY").box(50, 40, 30)
s1 = _place(s1, (0.0, 0.0, 15.0), (0.0, 0.0, 0.0))
result = result.union(s1)

# step 'outer_cyl_pp' — union cylinder
s2 = cq.Workplane("XY").cylinder(30, 5)
s2 = _place(s2, (25.0, 15.0, 15.0), (0.0, 0.0, 0.0))
result = result.union(s2)

# step 'outer_cyl_np' — union cylinder
s3 = cq.Workplane("XY").cylinder(30, 5)
s3 = _place(s3, (-25.0, 15.0, 15.0), (0.0, 0.0, 0.0))
result = result.union(s3)

# step 'outer_cyl_nn' — union cylinder
s4 = cq.Workplane("XY").cylinder(30, 5)
s4 = _place(s4, (-25.0, -15.0, 15.0), (0.0, 0.0, 0.0))
result = result.union(s4)

# step 'outer_cyl_pn' — union cylinder
s5 = cq.Workplane("XY").cylinder(30, 5)
s5 = _place(s5, (25.0, -15.0, 15.0), (0.0, 0.0, 0.0))
result = result.union(s5)

# step 'inner_box_1' — cut box
s6 = cq.Workplane("XY").box(50, 36, 29)
s6 = _place(s6, (0.0, 0.0, 16.5), (0.0, 0.0, 0.0))
result = result.cut(s6)

# step 'inner_box_2' — cut box
s7 = cq.Workplane("XY").box(56, 30, 29)
s7 = _place(s7, (0.0, 0.0, 16.5), (0.0, 0.0, 0.0))
result = result.cut(s7)

# step 'inner_cyl_pp' — cut cylinder
s8 = cq.Workplane("XY").cylinder(29, 3)
s8 = _place(s8, (25.0, 15.0, 16.5), (0.0, 0.0, 0.0))
result = result.cut(s8)

# step 'inner_cyl_np' — cut cylinder
s9 = cq.Workplane("XY").cylinder(29, 3)
s9 = _place(s9, (-25.0, 15.0, 16.5), (0.0, 0.0, 0.0))
result = result.cut(s9)

# step 'inner_cyl_nn' — cut cylinder
s10 = cq.Workplane("XY").cylinder(29, 3)
s10 = _place(s10, (-25.0, -15.0, 16.5), (0.0, 0.0, 0.0))
result = result.cut(s10)

# step 'inner_cyl_pn' — cut cylinder
s11 = cq.Workplane("XY").cylinder(29, 3)
s11 = _place(s11, (25.0, -15.0, 16.5), (0.0, 0.0, 0.0))
result = result.cut(s11)
