import cadquery as cq
import meshlib.mrmeshpy as mm
import tempfile
import os

hub = cq.Workplane('XY').cylinder(80, 50)
leg1 = cq.Workplane('XY').box(300, 50, 40).translate((175, 0, 20))
leg2 = cq.Workplane('XY').box(300, 50, 40).translate((175, 0, 20)).rotate((0,0,0),(0,0,1),72)
leg3 = cq.Workplane('XY').box(300, 50, 40).translate((175, 0, 20)).rotate((0,0,0),(0,0,1),144)
leg4 = cq.Workplane('XY').box(300, 50, 40).translate((175, 0, 20)).rotate((0,0,0),(0,0,1),216)
leg5 = cq.Workplane('XY').box(300, 50, 40).translate((175, 0, 20)).rotate((0,0,0),(0,0,1),288)

# With tol=1e-4
res = hub.union(leg1, tol=1e-4).union(leg2, tol=1e-4).union(leg3, tol=1e-4).union(leg4, tol=1e-4).union(leg5, tol=1e-4)

f = tempfile.mktemp(suffix=".stl")
cq.exporters.export(res, f)
mesh = mm.loadMesh(f)
os.remove(f)

print("MeshLib components:", int(mm.MeshComponents.getNumComponents(mesh)))
print("MeshLib self-intersections:", int(mm.findSelfCollidingTriangles(mm.MeshPart(mesh)).size()))
