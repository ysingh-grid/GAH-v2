import cadquery as cq

# --- dimensions straight from prompt.txt ---
L, W, H = 70.0, 50.0, 30.0  # outer length(X) x width(Y) x height(Z)
fillet_r = 4.0  # vertical-edge fillet
wall = 2.0  # shell wall thickness
boss_d, boss_h = 8.0, 28.0  # screw boss diameter / height
hole_d = 3.0  # through-hole diameter
bx, by = 27.0, 17.0  # boss offsets from center (X, Y) original value is 27x17

pts = [(bx, by), (bx, -by), (-bx, by), (-bx, -by)]  # 4 symmetric positions

# 1. outer body — base sits at Z=0 (centered XY, NOT centered Z)
body = cq.Workplane("XY").box(L, W, H, centered=(True, True, False))

# 2. fillet the 4 vertical edges (edges parallel to Z)
body = body.edges("|Z").fillet(fillet_r)

# 3. open the top (+Z) face and shell 2mm inward -> inner floor top = Z=2
body = body.faces(">Z").shell(-wall)

# 4. four solid bosses, from inner floor (Z=2) up to rim (Z=30)
bosses = (
    cq.Workplane("XY")
    .workplane(offset=wall)  # start plane at Z=2
    .pushPoints(pts)
    .circle(boss_d / 2.0)
    .extrude(boss_h)  # 28mm -> top at Z=30
)
result = body.union(bosses)

# 5. 3mm through-hole on each boss, drilled past boss AND bottom floor
holes = (
    cq.Workplane("XY")
    .workplane(offset=-1)  # start below the base
    .pushPoints(pts)
    .circle(hole_d / 2.0)
    .extrude(H + 2)  # overshoot top+bottom so cut is clean
)
result = result.cut(holes)  # `result` = what execute_cadquery exports
