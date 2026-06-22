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

# part: elliptical_cylinder (units: mm)
# step 'base_elliptical_cylinder' — base profile_extrude
s0 = cq.Workplane("XY").polyline([[20.0, 0.0], [19.9037, 0.9802], [19.6157, 1.9509], [19.1388, 2.9028], [18.4776, 3.8268], [17.6384, 4.714], [16.6294, 5.5557], [15.4602, 6.3439], [14.1421, 7.0711], [12.6879, 7.7301], [11.1114, 8.3147], [9.4279, 8.8192], [7.6537, 9.2388], [5.8057, 9.5694], [3.9018, 9.8079], [1.9603, 9.9518], [0.0, 10.0], [-1.9603, 9.9518], [-3.9018, 9.8079], [-5.8057, 9.5694], [-7.6537, 9.2388], [-9.4279, 8.8192], [-11.1114, 8.3147], [-12.6879, 7.7301], [-14.1421, 7.0711], [-15.4602, 6.3439], [-16.6294, 5.5557], [-17.6384, 4.714], [-18.4776, 3.8268], [-19.1388, 2.9028], [-19.6157, 1.9509], [-19.9037, 0.9802], [-20.0, 0.0], [-19.9037, -0.9802], [-19.6157, -1.9509], [-19.1388, -2.9028], [-18.4776, -3.8268], [-17.6384, -4.714], [-16.6294, -5.5557], [-15.4602, -6.3439], [-14.1421, -7.0711], [-12.6879, -7.7301], [-11.1114, -8.3147], [-9.4279, -8.8192], [-7.6537, -9.2388], [-5.8057, -9.5694], [-3.9018, -9.8079], [-1.9603, -9.9518], [0.0, -10.0], [1.9603, -9.9518], [3.9018, -9.8079], [5.8057, -9.5694], [7.6537, -9.2388], [9.4279, -8.8192], [11.1114, -8.3147], [12.6879, -7.7301], [14.1421, -7.0711], [15.4602, -6.3439], [16.6294, -5.5557], [17.6384, -4.714], [18.4776, -3.8268], [19.1388, -2.9028], [19.6157, -1.9509], [19.9037, -0.9802]]).close().extrude(25)
s0 = _place(s0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
result = s0
