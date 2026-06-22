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

// part: elliptical_cylinder (units: mm)
// step 'base_elliptical_cylinder' — base profile_extrude
let s0 = polygon([[20.0, 0.0], [19.9037, 0.9802], [19.6157, 1.9509], [19.1388, 2.9028], [18.4776, 3.8268], [17.6384, 4.714], [16.6294, 5.5557], [15.4602, 6.3439], [14.1421, 7.0711], [12.6879, 7.7301], [11.1114, 8.3147], [9.4279, 8.8192], [7.6537, 9.2388], [5.8057, 9.5694], [3.9018, 9.8079], [1.9603, 9.9518], [0.0, 10.0], [-1.9603, 9.9518], [-3.9018, 9.8079], [-5.8057, 9.5694], [-7.6537, 9.2388], [-9.4279, 8.8192], [-11.1114, 8.3147], [-12.6879, 7.7301], [-14.1421, 7.0711], [-15.4602, 6.3439], [-16.6294, 5.5557], [-17.6384, 4.714], [-18.4776, 3.8268], [-19.1388, 2.9028], [-19.6157, 1.9509], [-19.9037, 0.9802], [-20.0, 0.0], [-19.9037, -0.9802], [-19.6157, -1.9509], [-19.1388, -2.9028], [-18.4776, -3.8268], [-17.6384, -4.714], [-16.6294, -5.5557], [-15.4602, -6.3439], [-14.1421, -7.0711], [-12.6879, -7.7301], [-11.1114, -8.3147], [-9.4279, -8.8192], [-7.6537, -9.2388], [-5.8057, -9.5694], [-3.9018, -9.8079], [-1.9603, -9.9518], [0.0, -10.0], [1.9603, -9.9518], [3.9018, -9.8079], [5.8057, -9.5694], [7.6537, -9.2388], [9.4279, -8.8192], [11.1114, -8.3147], [12.6879, -7.7301], [14.1421, -7.0711], [15.4602, -6.3439], [16.6294, -5.5557], [17.6384, -4.714], [18.4776, -3.8268], [19.1388, -2.9028], [19.6157, -1.9509], [19.9037, -0.9802]]).extrude(25);
s0 = _place(s0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0);
let result = s0;

return { "elliptical_cylinder": result };