# ForgeCAD Agent Skill: CadQuery to ForgeCAD Translation Reference

You are an expert at translating Python CadQuery (CQ) scripts into direct, parametric ForgeCAD JavaScript (`.forge.js`).

---

## 🧠 The Core Paradigm Shift

1. **Stateful vs. Absolute**: 
   * **CadQuery**: Relies on a relative local coordinate system (Workplanes) and selections (e.g. `.faces(">Z")`).
   * **ForgeCAD**: Uses explicit absolute CSG modeling. You MUST construct your 3D shapes at the origin `(0,0,0)`, and then manually position them using `.translate(x, y, z)` and `.rotate(degX, degY, degZ)` before merging them.
2. **Method Chaining vs. Sequential Variables**: 
   * Avoid translating a long CQ chain in one go. Create separate, clearly named variables for the `base`, `additions`, and `cutters`, and combine them using method-based booleans (e.g. `base.add(part)` or `base.subtract(cutter)`).
3. **No Brittle Selectors**: 
   * ForgeCAD does not have selectors like `.faces(">Z")` or `.edges("|Z")`. You must calculate face dimensions and heights mathematically based on your variables/parameters.

---

## 📖 The Rosetta Stone (Direct Mappings)

### 1. Basic Primitives
*   **CQ**: `cq.Workplane("XY").box(width, depth, height)`
*   **ForgeCAD**: `let body = box(width, depth, height).placeReference('center', [0, 0, 0]);` (ForgeCAD boxes are centered on XY, sitting on Z=0 by default).
*   **CQ**: `cq.Workplane("XY").circle(radius).extrude(height)`
*   **ForgeCAD**: `let body = cylinder(radius, height);`

### 2. Drilling Holes (Relative Workplane cuts)
*   **CQ**:
    ```python
    plate = cq.Workplane("XY").box(100, 60, 6).faces(">Z").workplane().pushPoints([(0, 0)]).hole(5)
    ```
*   **ForgeCAD**: Construct the plate and the cutter cylinder separately. If plate height is `6`, a through-hole cutter should be slightly taller (e.g. height `16`) and translated so it spans the entire plate:
    ```javascript
    let plate = box(100, 60, 6).placeReference('center', [0, 0, 0]);
    let holeCutter = cylinder(2.5, 16).translate(0, 0, -5); // 2.5 is radius, 16 is height
    let finalPlate = plate.subtract(holeCutter);
    ```

### 3. Edge Rounding (Fillets & Chamfers)
*   **CQ (Vertical Edges)**: `cq.Workplane("XY").box(60, 40, 20).edges("|Z").fillet(4)`
*   **ForgeCAD**: In ForgeCAD, rounding vertical edges of a box is most cleanly done by extruding a 2D `roundedRect` instead of filleting a 3D block:
    ```javascript
    let block = roundedRect(60, 40, 4).extrude(20);
    ```
*   **CQ (Top Face Edges)**: `body.faces(">Z").edges().chamfer(1.2)`
*   **ForgeCAD**: Use the global `chamfer(shape, size)` or `fillet(shape, radius)` functions directly on the final 3D shape:
    ```javascript
    let finishedShape = chamfer(body, 1.2);
    ```

### 4. 2D Sketches & Outline Extrusion
*   **CQ**:
    ```python
    profile = cq.Workplane("XY").moveTo(0,0).lineTo(10,0).lineTo(10,20).close().extrude(5)
    ```
*   **ForgeCAD**:
    ```javascript
    let profile = polygon([ [0,0], [10,0], [10,20] ]).extrude(5);
    ```

### 5. Multi-Part Assemblies
*   **CQ**:
    ```python
    assembly = cq.Assembly().add(base, name="base").add(finger, name="finger")
    ```
*   **ForgeCAD**: Use the component `group()` format to organize multiple static bodies:
    ```javascript
    const assembly = group(
      { name: "base", shape: base },
      { name: "finger", shape: finger }
    );
    return assembly;
    ```

---

## 🛠️ Translation Workflow

1.  **Extract Parameters**: Turn Python variables or hardcoded dimensions into ForgeCAD `param("Name", value, { unit: "mm" })` statements at the top of the file to preserve parametric design.
2.  **Manually Calculate Placements**: If CQ places features using relative points, do the math to map those to absolute values. E.g. translation to `plate_thickness / 2` or `height - depth`.
3.  **Use Positional Arguments**: ForgeCAD strictly forbids arrays inside transformations. ALWAYS translate with `.translate(x, y, z)` instead of `.translate([x, y, z])`.
4.  **End with Return**: Always conclude the script with a top-level `return <final_shape_or_group>;`.
