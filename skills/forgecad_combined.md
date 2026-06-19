# ForgeCAD Agent Skill: Solid Triangle Generation

This skill guides the agent to author a valid, compile-ready solid triangle (triangular prism) script and compile it to STL.

---

# CRITICAL COMPILER RULES
- DO NOT WRITE FUNCTIONS OF ANY KIND! Do not use `function main() { ... }`, do not define custom functions, and do not use function wrappers.
- The script must consist ONLY of top-level, sequential global variable declarations and expressions.
- The script must end with a top-level `return triangle;` statement to render the shape.
- Primitives use positional arguments: `ngon(3, radius)` and `.extrude(height)`.

---

# EXPLICIT CODE TEMPLATE
You MUST write exactly this code to `bracket.forge.js`:
```javascript
const radius = 30;
const height = 10;
const triangle = ngon(3, radius).extrude(height);
return triangle;
```

---

# WORKFLOW
1. Write exactly the code template above to `bracket.forge.js` using `write_workspace_file`.
2. Compile `bracket.forge.js` to `bracket.stl` using `export_forgecad_to_stl`.
3. Return success: true and compilation logs on success.
