"""Legacy entrypoint kept for discoverability.

The old backend-bridge RLM demo has been removed. In the current architecture,
RLM plans with primitive/skill context only, while the CAD pipeline runs
directly on the host.
"""


def main() -> None:
    raise SystemExit(
        "The backend-bridge geometry demo was removed.\n"
        "Use the current host-run pipeline instead:\n"
        "  python -m uvicorn backend.server:app --host 127.0.0.1 --port 8001\n"
        "  export GEMINI_API_KEY=your_key_here\n"
        "  python Task_test.py\n"
        "  python Task_test_complex.py"
    )


if __name__ == "__main__":
    main()
