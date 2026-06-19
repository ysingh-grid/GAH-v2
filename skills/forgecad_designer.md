# ForgeCAD Generation Skill

Use this skill to generate direct ForgeCAD `.forge.js` models and compile them with the host tools.

## Hard Constraints

- Generate ForgeCAD JavaScript only. Never use CadQuery, Python CAD code, OpenSCAD, JSCAD, `CSG`, `@jscad/modeling`, or `modeling.primitives`.
- Do not create local shims or variables named `difference`, `union`, `cube`, `box`, `cylinder`, `chamfer`, `fillet`, or other ForgeCAD globals. ForgeCAD injects its API globals directly.
- Do not import ForgeCAD API names. Use injected globals directly: `box(...)`, `cylinder(...)`, `param(...)`, `group(...)`, `assembly(...)`.
- Do not print full docs, schema, role instructions, or context. Only print concise debugging output if a compile error needs repair.
- Do not create scratch output folders. Write only `outputs/<design_name>/model.forge.js` through the combined host tool.
- Do not use silent `try/catch` fallbacks in generated code. If geometry must be simplified, make the simplification explicit.
- Every generated `.forge.js` file must end with a top-level `return <shape_or_renderable>;`.
- **CRITICAL ANTI-HALLUCINATION LOOKUP RULE**: NEVER guess, invent, or assume the name, existence, or signature of any ForgeCAD function, method, class, or parameter. If you have even a shadow of doubt:
  1. You MUST call `forgecad_api_lookup(symbol)` or `forgecad_web_doc_lookup(topic)` to verify the exact definition, existence, and signature of that symbol in the reference codebase before writing it in your code!
  2. If the lookup returns a local-miss or does not exist, DO NOT write that function. Switch to a standard, verified primitive (like `box` or `cylinder`) that you have confirmed through doc lookups.
  3. Writing non-existent or unverified functions will crash the compiler and immediately fail your validation checks.

## Workflow

1. Discover host tools using `mcp_list_tools()`.
2. Generate a structured plan for the prompt using `forgecad_decompose_prompt(prompt)`.
3. Select a short kebab-case `design_name`.
4. If you are unsure of any API signatures, call `forgecad_api_lookup(symbol)` first to verify them. NEVER GUESS.
5. Author one sequential top-level ForgeCAD `.forge.js` script that returns the final shape or grouped assembly.
6. Call `forgecad_code_lint(js_content)` and resolve all lint issues before compilation.
7. Compile and export the model using `write_and_export_forgecad_model(design_name, js_content)`.
8. If compilation fails, analyze the error logs, repair the code, and re-export.
9. Return the final successfully compiled result matching `schemas/cad_generation.py`.

## Terminal Trace

- Print a visible `Reasoning summary:` before major actions.
- Print tool names and compact arguments before tool calls.
- Print tool output summaries and full compiler errors.
- Do not print hidden chain-of-thought or full docs/context.

## Authoring Rules

- Use `param("Name", defaultValue, { min, max, unit: "mm" })` when the prompt says "parametric" or asks for adjustable dimensions.
- Use millimeters and degrees unless the prompt specifies otherwise.
- ForgeCAD 3D primitives are centered on XY with base at `Z=0`; use `.placeReference('center', [0, 0, 0])` when the whole part must be centered at the origin.
- Use method booleans on shapes: `shapeA.subtract(shapeB)`, `shapeA.add(shapeB)`, `shapeA.intersect(shapeB)`.
- **CRITICAL TRANSLATION/ROTATION SYNTAX RULE**: NEVER pass an array to `.translate([x, y, z])` or `.rotate([degX, degY, degZ])`. In ForgeCAD, these methods take separate positional arguments: `.translate(x, y, z)` and `.rotate(degX, degY, degZ)`. Passing an array makes Y and Z undefined (`NaN`), which will corrupt the coordinates and trigger extremely confusing compiler errors like "edges.top-rim.start must contain finite numbers". Always use separate numbers: `.translate(hx, hy, 0)`!
- Use `shape.rotate(degX, degY, degZ)` or `.rotateX/Y/Z(angleDeg)` and `pointAlong([dx, dy, dz])` when documented.
- For multi-part static models, return named objects or `group(...)`; for mechanisms, use `assembly(...)` and joints from the routed Assembly docs.
- For sketch profiles, use `rect(...)`, `circle2d(...)`, `ngon(...)`, `polygon(...)`, `roundedRect(...)`, `slot(...)`, `union2d(...)`, and `.extrude(...)`.
- **CRITICAL CHAMFER/FILLET RULE**: Do NOT attempt to use edge selectors like `shape.edge("top-rim")` or `chamferTrackedEdge` on extruded shapes, as they will cause `edges.top-rim.start must contain finite numbers` errors. To chamfer or fillet a 3D solid, use the global `chamfer(shape, radius)` or `fillet(shape, radius)` functions directly (e.g., `let plate = chamfer(box(100, 80, 5), 1);`).
- When using `roundedRect(width, height, radius)`, simply `.extrude(height)` it to make it 3D. Do NOT attempt to combine it with complex 3D edge selectors.

## Safe Minimal Pattern

```javascript
const width = param("Width", 60, { min: 10, max: 200, unit: "mm" });
const depth = param("Depth", 40, { min: 10, max: 200, unit: "mm" });
const height = param("Height", 20, { min: 5, max: 100, unit: "mm" });

const body = box(width, depth, height).placeReference('center', [0, 0, 0]);
return body;
```

---

## 🧠 COGNITIVE DEBUGGING PROTOCOL (HYPOTHESIS TESTING)

When a compilation or export fails, DO NOT randomly edit code or read unrelated files. You must operate like a senior software engineer and use your intelligence to debug systematically:

1. **Locate and Isolate**: Identify the exact line number of the error (e.g., `model.forge.js:12`).
2. **Formulate Hypotheses**: Brainstorm reasons for the failure, such as:
   - *Parameter Mismatches*: Did you pass an array `[x, y, z]` instead of positional arguments `(x, y, z)`? Did you pass options dictionaries to primitives?
   - *Undefined Values*: Did a translation coordinate evaluate to `NaN` or `undefined`?
   - *Unsupported Methods*: Are you trying to call a method (like edge tracking) that doesn't exist on that specific object class?
3. **Verify Signatures Programmatically**: Call `forgecad_api_lookup(symbol)` for any function, primitive, or method on that line to check its exact expected argument types, signatures, and constraints. Never guess!
4. **Empirical Isolation (Tiny Snippets)**: Write a tiny 2-line standalone test script in Python to isolate and test the suspect API call (e.g. `return cylinder(5, 10).translate([0,0,0]);`). Compile it using the host tools. If it fails, you have isolated the bug!
5. **Iterate & Repair**: Once the tiny snippet succeeds, apply the proven correct syntax back to your main script. This scientific approach guarantees success and prevents infinite loop crashes.
