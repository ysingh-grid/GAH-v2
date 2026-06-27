import meshlib.mrmeshpy as mm

mesh = mm.loadMesh("test_gear.stl")
components = mesh.getValidFaces().getComponents()
print(f"Number of components: {len(components)}")
for i, comp in enumerate(components):
    cmesh = mm.Mesh(mesh)
    cmesh.topology.filterValidFaces(comp)
    mm.saveMesh(cmesh, f"test_gear_comp_{i}.stl")
    print(f"Component {i} volume: {cmesh.computeVolume()}")
