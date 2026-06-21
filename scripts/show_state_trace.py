import json
from pathlib import Path


REPORT_PATH = Path("generated/rlm_full_demo_report.json")


def main():
    if not REPORT_PATH.exists():
        raise SystemExit("Run python scripts/run_full_rlm_backend_demo.py first.")

    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    print(f"Report: {REPORT_PATH}")
    print(f"Backend URL: {report.get('backend_url')}")
    print(f"Repo file count: {report.get('repo_file_count')}")
    print(f"Loaded skills: {', '.join(report.get('loaded_skills', []))}")
    print(f"Selected primitives: {', '.join(report.get('selected_primitives', []))}")
    print()
    print("State Trace")
    print("-----------")

    for entry in report.get("state_trace", []):
        response = entry.get("response_contract", {})
        parsed = entry.get("parsed_by_rlm_tool", {})
        print(f"{entry.get('step')}. {entry.get('rlm_tool')} -> {entry.get('backend_endpoint')}")
        print(f"   request: {json.dumps(entry.get('request', {}), sort_keys=True)}")
        print(
            "   response: "
            f"ok={response.get('ok')} tool={response.get('tool')} "
            f"data_keys={response.get('data_keys', response.get('data_type'))}"
        )
        print(f"   parsed: {json.dumps(parsed, sort_keys=True)}")


if __name__ == "__main__":
    main()
