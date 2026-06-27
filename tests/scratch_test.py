import json
import sys
from pathlib import Path
import cadquery as cq

sys.path.append('/Users/makumar/Documents/v3_capstone_ds_06')
from cad_kernel import kernel

log_file = Path('/Users/makumar/Documents/v3_capstone_ds_06/logs/geometry_planning_repair_a1_2026-06-22T17-21-43-063Z.jsonl')

with open(log_file, 'r') as f:
    lines = f.readlines()
    last_line = json.loads(lines[-2]) 
    
plan = last_line.get('result', {})

print("Building plan...")
br = kernel.build_plan(plan)
if not br['ok']:
    print(f"Build failed: {br.get('failed_step')}")
    sys.exit(1)

solid = br["solid"]

export_dir = Path('/Users/makumar/Documents/v3_capstone_ds_06/exports')
export_dir.mkdir(exist_ok=True)
base_filename = f"output_{plan.get('title', 'untitled').replace(' ', '_')[:60]}"
stl_path = export_dir / f"{base_filename}.stl"
step_path = export_dir / f"{base_filename}.step"

cq.exporters.export(solid, str(stl_path))
cq.exporters.export(solid, str(step_path))

print(f"CAD files exported successfully to:")
print(f"  - {stl_path}")
print(f"  - {step_path}")
