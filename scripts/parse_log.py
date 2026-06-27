import json

log_file = "/Users/makumar/Documents/v3_capstone_ds_06/logs/geometry_planning_repair_a3_2026-06-23T05-55-21-400Z.jsonl"
found = False
with open(log_file, "r") as f:
    for line in f:
        data = json.loads(line)
        if "steps" in data:
            for step in data["steps"]:
                for tool in step.get("tool_calls", []):
                    if tool.get("name") in ["FINAL", "validate_plan"]:
                        args = tool.get("args", {})
                        if "plan" in args:
                            with open("latest_plan.json", "w") as out:
                                json.dump(args["plan"], out, indent=2)
                            found = True
if found:
    print("latest_plan.json created.")
else:
    print("Plan not found.")
