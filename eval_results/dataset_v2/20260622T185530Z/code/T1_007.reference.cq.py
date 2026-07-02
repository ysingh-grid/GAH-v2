import cadquery as cq
import math
result = cq.Workplane('XY').polygon(6, 20).extrude(35)