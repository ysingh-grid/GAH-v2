"""Patch fast_rlm's engine so LLM calls cannot hang past their deadline.

WHY THIS EXISTS (measured live, 2026-07-10):
  Replanner runs stalled 2484s / 2184s / 1056s / 1011s inside SINGLE
  `chat.completions.create` calls despite `api_timeout_ms=120000` reaching the
  engine correctly. Empirical isolation against local test servers:
    - connection that never returns headers  -> client timeout fires (~6s
      with retries). Works.
    - connection that returns HEADERS then stalls/trickles the BODY -> the
      openai@4 client's `timeout` option NEVER fires; the call hangs until the
      remote load balancer drops it (Gemini: ~40 min). This is the hang.
    - the same trickling body wrapped in an AbortController deadline passed as
      a per-request `signal` -> aborts at exactly the deadline. This is the fix.

  The hung calls came back with ~15 completion tokens and no ```repl block
  (connection scraps), which the engine then "could not extract code"-looped
  on — the observed slowness AND unreliability share this one root cause.

WHY A PATCH SCRIPT AND NOT A FORK/VENDORING:
  fast-rlm is a pinned PyPI dep (0.1.18, hash-locked in uv.lock). Vendoring the
  whole engine to change 1 call site would orphan us from upstream. This script
  is idempotent (marker-guarded), verifies the anchor it patches still exists,
  and FAILS LOUDLY if the engine changed — so a future fast-rlm upgrade cannot
  silently reintroduce the hang.

WHERE IT RUNS:
  - Dockerfile: right after `uv sync`, against the image's site-packages.
  - Local dev: `python3 patches/patch_fast_rlm_deadline.py` once per env.

The retry stays INSIDE generate_code: on deadline it aborts and retries fresh
(maxRetries+1 attempts total, so worst case = (api_max_retries+1) x
api_timeout_ms, currently 3 x 120s = 360s per LLM call). Only after every
attempt fails does it raise — and that surfaces to Temporal, whose activity
retry policy re-runs the planner. The run is never left hanging.
"""

from __future__ import annotations

import sys
from pathlib import Path

MARKER = "[GAH PATCH: whole-call deadline]"

ANCHOR = "        const completion = await client.chat.completions.create(createParams);"

REPLACEMENT = """        // [GAH PATCH: whole-call deadline] The client's `timeout` option only
        // aborts requests that never return HEADERS; once the provider starts
        // (or stalls) the response BODY, no timer covers the read and a call
        // can hang for 40+ minutes (measured live: 2484s for a reply of 12
        // completion tokens). An AbortController deadline passed as the
        // per-request `signal` covers the FULL call including the body read
        // (verified: aborts a trickling body at exactly the deadline). On
        // abort we retry fresh instead of returning connection scraps.
        // deno-lint-ignore no-explicit-any
        let completion: any = null;
        {
            const attempts = maxRetries + 1;
            for (let attempt = 0; ; attempt++) {
                const ctrl = new AbortController();
                const timer = setTimeout(() => ctrl.abort(), timeout);
                try {
                    completion = await client.chat.completions.create(
                        createParams, { signal: ctrl.signal });
                    break;
                } catch (err) {
                    if (attempt >= attempts - 1) throw err;
                    console.error(chalk.yellow(
                        `\\u26a0 LLM call attempt ${attempt + 1}/${attempts} ` +
                        `failed (${String(err).slice(0, 120)}); retrying fresh`));
                } finally {
                    clearTimeout(timer);
                }
            }
        }"""


def patch() -> int:
    try:
        import fast_rlm
    except ImportError:
        print("patch_fast_rlm_deadline: fast_rlm not importable in this env", file=sys.stderr)
        return 1

    target = Path(fast_rlm.__file__).parent / "_engine" / "src" / "call_llm.ts"
    if not target.exists():
        print(f"patch_fast_rlm_deadline: engine file missing: {target}", file=sys.stderr)
        return 1

    src = target.read_text()
    if MARKER in src:
        print(f"patch_fast_rlm_deadline: already patched: {target}")
        return 0
    if ANCHOR not in src:
        print(
            "patch_fast_rlm_deadline: ANCHOR NOT FOUND — fast_rlm's engine changed "
            f"(upgrade?). Re-verify the hang still exists and update this patch.\n"
            f"  file: {target}",
            file=sys.stderr,
        )
        return 1
    if src.count(ANCHOR) != 1:
        print(
            f"patch_fast_rlm_deadline: anchor matched {src.count(ANCHOR)} times, "
            "expected exactly 1 — refusing to guess.",
            file=sys.stderr,
        )
        return 1

    target.write_text(src.replace(ANCHOR, REPLACEMENT))
    print(f"patch_fast_rlm_deadline: patched {target}")
    return 0


if __name__ == "__main__":
    sys.exit(patch())
