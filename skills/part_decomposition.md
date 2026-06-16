# Skill: Part Decomposition

This guide details how to decompose a complex 3D shape into a sequence of operations involving simple primitive shapes (Constructive Solid Geometry).

## Principles of Solid Decomposition

Most complex mechanical parts can be represented as:
`Base Solid (+ Addition Solids) (- Subtraction Solids)`

1. **Identify the Base Solid**:
   - What is the largest/dominant primitive shape? (e.g. the main block of a bracket, the main cylinder of a flange).
   - This should always be the starting point in the construction tree.

2. **Identify Features (Additions)**:
   - What shapes are fused/joined to the base? (e.g. boss extrusions, ribs, tabs).
   - Represent these as primitive solid additions (`union` operations).

3. **Identify Pockets (Subtractions)**:
   - What shapes are carved out of the base? (e.g. holes, slots, counterbores, pockets).
   - Represent these as negative primitive solid subtractions (`cut` or `difference` operations).

4. **Identify Finish Features**:
   - Fillets, chamfers, and shells.
   - These are always applied at the end of the decomposition sequence.

## Example: Flanged Mount

- **Base**: Cylinder (`outer_radius=50`, `height=10`)
- **Addition**: Cylinder (`outer_radius=25`, `height=30`) joined at center Z-offset.
- **Subtraction**: Cylinder (`outer_radius=15`, `height=40`) centered to make it hollow.
- **Subtraction**: Circular pattern of 4 holes (`radius=3.3`, `height=10`, radial offset `38`).
- **Finish**: Chamfer outer top edge `1mm`.
