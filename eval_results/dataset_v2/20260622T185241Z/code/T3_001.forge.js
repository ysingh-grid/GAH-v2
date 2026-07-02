// GAH-v2 generated .forge.js — do not edit; regenerate from plan
// Helpers ─────────────────────────────────────────────────────────────────────
function _place(shape, px, py, pz, rx, ry, rz) {
  let s = shape;
  // ForgeCAD Shape.rotate signature is rotate(axis, angleDeg) — axis FIRST.
  if (rx !== 0) s = s.rotate([1, 0, 0], rx);
  if (ry !== 0) s = s.rotate([0, 1, 0], ry);
  if (rz !== 0) s = s.rotate([0, 0, 1], rz);
  if (px !== 0 || py !== 0 || pz !== 0) s = s.translate(px, py, pz);
  return s;
}
function _polar(shape, count, ax, ay, az, angle_deg) {
  const step = angle_deg / count;
  const copies = Array.from({ length: count }, (_, k) =>
    shape.rotate([ax, ay, az], k * step)
  );
  return union(...copies);
}
function _linear(shape, count, sx, sy, sz) {
  const copies = Array.from({ length: count }, (_, k) =>
    shape.translate(sx * k, sy * k, sz * k)
  );
  return union(...copies);
}
function _torus(ring_r, tube_r) {
  // Approximate torus: polygon profile of a circle at ring_r, revolved around Y.
  const pts = [];
  const steps = 32;
  for (let i = 0; i < steps; i++) {
    const a = (i / steps) * Math.PI * 2;
    pts.push([ring_r + tube_r * Math.cos(a), tube_r * Math.sin(a)]);
  }
  return polygon(pts).revolve();
}
function _ellipsoid(xr, zr) {
  // Half-ellipse profile revolved around Y axis.
  const pts = [[0, -zr]];
  const steps = 32;
  for (let i = 1; i <= steps; i++) {
    const a = (i / steps) * Math.PI;
    pts.push([xr * Math.sin(a), -zr * Math.cos(a)]);
  }
  return polygon(pts).revolve();
}
function _wedge(dx, dy, dz, xmin, ymin, xmax, ymax) {
  // Exact CadQuery/OCC makeWedge: box dx×dy×dz whose top face (y=dy) is shrunk
  // to the rect [xmin,xmax]×[ymin,ymax] (OCC's z-range). Built as a loft from the
  // full bottom rect to the offset top rect along Z, then rotated so the loft axis
  // becomes +Y (CadQuery's frame) and centered. Vertices match CadQuery exactly.
  const bottom = rect(dx, dz);
  const tw = Math.max(0.001, xmax - xmin), th = Math.max(0.001, ymax - ymin);
  const cx = (xmin + xmax) / 2 - dx / 2, cy = dz / 2 - (ymin + ymax) / 2;
  const top = rect(tw, th).translate(cx, cy);
  return loft([bottom, top], [0, dy]).rotate([1, 0, 0], -90).translate(0, -dy / 2, 0);
}
// ─────────────────────────────────────────────────────────────────────────────

// part: open_top_rounded_container (units: mm)
// step 'outer_box_base' — base box
let s0 = box(60, 30, 30).translate(0, 0, -30/2);
s0 = _place(s0, 0.0, 0.0, 15.0, 0.0, 0.0, 0.0);
let result = s0;

// step 'outer_box_union' — union box
let s1 = box(50, 40, 30).translate(0, 0, -30/2);
s1 = _place(s1, 0.0, 0.0, 15.0, 0.0, 0.0, 0.0);
result = result.add(s1);

// step 'outer_cyl_pp' — union cylinder
let s2 = cylinder(30, 5).translate(0, 0, -30/2);
s2 = _place(s2, 25.0, 15.0, 15.0, 0.0, 0.0, 0.0);
result = result.add(s2);

// step 'outer_cyl_np' — union cylinder
let s3 = cylinder(30, 5).translate(0, 0, -30/2);
s3 = _place(s3, -25.0, 15.0, 15.0, 0.0, 0.0, 0.0);
result = result.add(s3);

// step 'outer_cyl_nn' — union cylinder
let s4 = cylinder(30, 5).translate(0, 0, -30/2);
s4 = _place(s4, -25.0, -15.0, 15.0, 0.0, 0.0, 0.0);
result = result.add(s4);

// step 'outer_cyl_pn' — union cylinder
let s5 = cylinder(30, 5).translate(0, 0, -30/2);
s5 = _place(s5, 25.0, -15.0, 15.0, 0.0, 0.0, 0.0);
result = result.add(s5);

// step 'inner_box_1' — cut box
let s6 = box(50, 36, 29).translate(0, 0, -29/2);
s6 = _place(s6, 0.0, 0.0, 16.5, 0.0, 0.0, 0.0);
result = result.subtract(s6);

// step 'inner_box_2' — cut box
let s7 = box(56, 30, 29).translate(0, 0, -29/2);
s7 = _place(s7, 0.0, 0.0, 16.5, 0.0, 0.0, 0.0);
result = result.subtract(s7);

// step 'inner_cyl_pp' — cut cylinder
let s8 = cylinder(29, 3).translate(0, 0, -29/2);
s8 = _place(s8, 25.0, 15.0, 16.5, 0.0, 0.0, 0.0);
result = result.subtract(s8);

// step 'inner_cyl_np' — cut cylinder
let s9 = cylinder(29, 3).translate(0, 0, -29/2);
s9 = _place(s9, -25.0, 15.0, 16.5, 0.0, 0.0, 0.0);
result = result.subtract(s9);

// step 'inner_cyl_nn' — cut cylinder
let s10 = cylinder(29, 3).translate(0, 0, -29/2);
s10 = _place(s10, -25.0, -15.0, 16.5, 0.0, 0.0, 0.0);
result = result.subtract(s10);

// step 'inner_cyl_pn' — cut cylinder
let s11 = cylinder(29, 3).translate(0, 0, -29/2);
s11 = _place(s11, 25.0, -15.0, 16.5, 0.0, 0.0, 0.0);
result = result.subtract(s11);

return { "open_top_rounded_container": result };