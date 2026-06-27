"""
ui_server.py — a MINIMAL local test UI for ForgeCAD (testing only, not production).

Run it from the project venv:

    python ui_server.py            # then open the printed http://127.0.0.1:8765/ in a browser

Flow (one page):
  1. Type a design prompt and upload a REFERENCE IMAGE of the object you want, then "Get questions".
  2. The clarifier's questions appear in the page; type your answers.
  3. "Run" launches the full pipeline. Progress streams to THIS TERMINAL (where you started the
     server). The page shows status and, when finished, the verdict + render/export paths.

No external web framework — pure standard library. Single run at a time (testing).
"""

import cgi
import html
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
REFS = ROOT / "refs"
REFS.mkdir(exist_ok=True)
LOGS = ROOT / "logs"

import orchestrator  # noqa: E402

# Single-run state (testing tool — one run at a time).
_RUN = {"status": "idle", "result": None, "error": None, "prompt": None,
        "log": [], "start_ts": 0.0}
_LOCK = threading.Lock()


class _Tee:
    """Write to the real terminal AND capture into the per-run log buffer, so the UI can show the
    high-level narrative live (clarify / reference / build / verify / verdict prints)."""
    def __init__(self, real):
        self._real = real

    def write(self, s):
        try:
            self._real.write(s)
        except Exception:
            pass
        if s and s.strip():
            with _LOCK:
                for ln in s.rstrip("\n").split("\n"):
                    _RUN["log"].append(ln)
                if len(_RUN["log"]) > 600:
                    del _RUN["log"][:200]
        return len(s)

    def flush(self):
        try:
            self._real.flush()
        except Exception:
            pass


def _current_log_file(since_ts):
    """Newest fast-rlm planning JSONL log produced by THIS run (mtime at/after start)."""
    try:
        cands = [p for p in LOGS.glob("geometry_planning_*.jsonl")
                 if p.stat().st_mtime >= (since_ts - 2)]
        return max(cands, key=lambda p: p.stat().st_mtime) if cands else None
    except Exception:
        return None


def _trace_lines(log_file, limit=60):
    """Parse the agent's JSONL log into a compact, human-readable timeline: per step the first
    meaningful line of code it ran + a short tail of its output, plus error/FINAL markers."""
    out = []
    if not log_file:
        return out
    try:
        for line in open(log_file, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            et = e.get("event_type")
            step = e.get("step")
            depth = int(e.get("depth", 0) or 0)
            ind = "  " * depth
            if et == "agent_start":
                out.append(f"{ind}* agent start (depth {depth})")
            elif et in ("execution_result", "code_generated"):
                if step == 0:
                    continue
                code = (e.get("code") or "").strip().splitlines()
                first = next((c for c in code if c.strip() and not c.strip().startswith("#")),
                             (code[0] if code else ""))
                out.append(f"{ind}- step {step}: {first.strip()[:110]}")
                o = (e.get("output") or "").strip()
                if o:
                    out.append(f"{ind}    -> {o[-240:].replace(chr(10), ' ')}")
                if e.get("hasError"):
                    out.append(f"{ind}    !! error in step {step}")
            elif et == "final_result":
                out.append(f"{ind}== FINAL ==")
    except Exception:
        return out
    return out[-limit:]


def _config():
    return orchestrator.load_run_config()


def _page(body: str) -> bytes:
    return (f"""<!doctype html><html><head><meta charset="utf-8"><title>ForgeCAD test UI</title>
<style>
 body{{font-family:system-ui,Arial,sans-serif;max-width:760px;margin:32px auto;padding:0 16px;color:#1a1a1a}}
 h1{{font-size:20px}} label{{display:block;margin:12px 0 4px;font-weight:600}}
 textarea,input[type=text]{{width:100%;padding:8px;font-size:14px;box-sizing:border-box}}
 textarea{{height:70px}} button{{margin-top:16px;padding:10px 18px;font-size:14px;cursor:pointer}}
 .q{{background:#f4f4f4;padding:10px;border-radius:6px;margin:10px 0}}
 .note{{color:#666;font-size:13px}} .ok{{color:#137333}} .err{{color:#b00020;white-space:pre-wrap}}
 code{{background:#eee;padding:1px 4px}}
 h2{{font-size:15px;margin-top:22px}}
 .box{{background:#0e0e0e;color:#d6d6d6;padding:10px;border-radius:6px;max-height:340px;
   overflow:auto;font-size:12px;line-height:1.45;white-space:pre-wrap;word-break:break-word}}
</style></head><body>{body}</body></html>""").encode("utf-8")


def _home() -> bytes:
    return _page("""
<h1>ForgeCAD &mdash; test UI</h1>
<p class="note">Type a request, upload a reference image of the target object, then get clarifying
questions. The run streams to the terminal you launched this from.</p>
<form method="POST" action="/clarify" enctype="multipart/form-data">
  <label>Design prompt</label>
  <textarea name="prompt" placeholder="e.g. design an ergonomic office chair"></textarea>
  <label>Reference image (the object you want)</label>
  <input type="file" name="image" accept="image/*">
  <button type="submit">Get clarifying questions &rarr;</button>
</form>""")


def _clarify_page(prompt: str, image_path: str, questions: list) -> bytes:
    if questions:
        qrows = ""
        for i, q in enumerate(questions):
            qrows += (f'<div class="q"><label>{html.escape(q)}</label>'
                      f'<input type="hidden" name="q_{i}" value="{html.escape(q)}">'
                      f'<input type="text" name="a_{i}" placeholder="your answer"></div>')
    else:
        qrows = '<p class="note">No clarifying questions — the request is well specified.</p>'
    img_note = (f'<p class="note ok">reference image saved: <code>{html.escape(image_path)}</code></p>'
                if image_path else
                '<p class="note err">no image uploaded — proceeding without a reference.</p>')
    return _page(f"""
<h1>Clarify, then run</h1>
<p><b>Prompt:</b> {html.escape(prompt)}</p>{img_note}
<form method="POST" action="/run">
  <input type="hidden" name="prompt" value="{html.escape(prompt)}">
  <input type="hidden" name="image_path" value="{html.escape(image_path or '')}">
  <input type="hidden" name="n" value="{len(questions)}">
  {qrows}
  <button type="submit">Run pipeline &#9654;</button>
</form>
<p class="note">After clicking Run, watch the terminal. <a href="/status">Check status</a>.</p>""")


def _status_page() -> bytes:
    with _LOCK:
        st = dict(_RUN)
        narrative = list(_RUN["log"])[-120:]
        start_ts = _RUN["start_ts"]
    refresh = "<meta http-equiv='refresh' content='3'>" if st["status"] == "running" else ""
    body = f"{refresh}<h1>Status: {html.escape(st['status'])}</h1>"
    body += f"<p class='note'>prompt: {html.escape(str(st.get('prompt')))}</p>"

    # (b) the agent's actual step-by-step actions (live, from the run's JSONL log)
    steps = _trace_lines(_current_log_file(start_ts)) if start_ts else []
    if steps:
        body += "<h2>What the AI is doing (live)</h2><pre class='box'>" + \
                html.escape("\n".join(steps)) + "</pre>"

    if st["status"] == "done" and st["result"]:
        r = st["result"]
        body += (f"<p class='ok'>Verdict: {html.escape(str(r.get('verdict')))} | "
                 f"Trust: {html.escape(str(r.get('trust_tier')))}</p>"
                 f"<p>Title: {html.escape(str(r.get('title')))}</p>"
                 f"<p>Render: <code>{html.escape(str(r.get('render')))}</code></p>"
                 "<p>Exports:<br>" + "<br>".join(f"<code>{html.escape(str(e))}</code>"
                                                  for e in (r.get('exports') or [])) + "</p>")
    elif st["status"] == "failed":
        body += f"<p class='err'>FAILED: {html.escape(str(st.get('error')))}</p>"

    # (a) the high-level narrative (orchestrator prints captured live)
    if narrative:
        body += "<h2>Pipeline log</h2><pre class='box'>" + \
                html.escape("\n".join(narrative)) + "</pre>"
    if st["status"] == "running":
        body += "<p class='note'>Running &mdash; this page auto-refreshes every 3s (full detail also "
        body += "streams to the terminal).</p>"
    body += '<p><a href="/">&larr; new run</a></p>'
    return _page(body)


def _do_run(prompt, established_qa, image_path):
    with _LOCK:
        _RUN.update(status="running", result=None, error=None, prompt=prompt,
                    log=[], start_ts=time.time())
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = _Tee(old_out)
    try:
        result = orchestrator.run_pipeline(prompt, established_qa,
                                           reference_image_path=image_path or None)
        with _LOCK:
            _RUN.update(status="done", result=result)
    except orchestrator.PipelineError as e:
        with _LOCK:
            _RUN.update(status="failed", error=str(e))
    except Exception as e:
        with _LOCK:
            _RUN.update(status="failed", error=f"{type(e).__name__}: {e}")
    finally:
        sys.stdout, sys.stderr = old_out, old_err


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass

    def do_GET(self):
        self._send(_status_page() if self.path.startswith("/status") else _home())

    def do_POST(self):
        if self.path.startswith("/clarify"):
            fs = cgi.FieldStorage(fp=self.rfile, headers=self.headers,
                                  environ={"REQUEST_METHOD": "POST",
                                           "CONTENT_TYPE": self.headers.get("Content-Type", "")})
            prompt = (fs.getfirst("prompt") or "").strip()
            image_path = ""
            if "image" in fs and getattr(fs["image"], "filename", None):
                item = fs["image"]
                ext = os.path.splitext(item.filename)[1] or ".png"
                image_path = str(REFS / f"ref_{int(time.time())}{ext}")
                with open(image_path, "wb") as f:
                    f.write(item.file.read())
            if not prompt:
                self._send(_page("<p class='err'>Please enter a prompt.</p><a href='/'>back</a>"))
                return
            try:
                config, llm_kwargs, flags = _config()
                questions = orchestrator.generate_clarification_questions(prompt, config, llm_kwargs, flags)
            except Exception as e:
                print(f"[ui] question generation failed: {e}")
                questions = []
            self._send(_clarify_page(prompt, image_path, questions))

        elif self.path.startswith("/run"):
            from urllib.parse import parse_qs
            length = int(self.headers.get("Content-Length", 0))
            data = parse_qs(self.rfile.read(length).decode("utf-8"))
            prompt = (data.get("prompt", [""])[0]).strip()
            image_path = (data.get("image_path", [""])[0]).strip()
            n = int(data.get("n", ["0"])[0] or 0)
            established_qa = []
            for i in range(n):
                q = (data.get(f"q_{i}", [""])[0]).strip()
                a = (data.get(f"a_{i}", [""])[0]).strip()
                if q and a:
                    established_qa.append({"question": q, "answer": a})
            with _LOCK:
                busy = _RUN["status"] == "running"
            if busy:
                self._send(_page("<p class='err'>A run is already in progress. "
                                 "<a href='/status'>status</a></p>"))
                return
            threading.Thread(target=_do_run, args=(prompt, established_qa, image_path),
                             daemon=True).start()
            self._send(_page("<meta http-equiv='refresh' content='1;url=/status'>"
                             "<h1>Started &#9654;</h1><p>Opening the live view&hellip; "
                             "(<a href='/status'>/status</a>). Full detail also streams to the terminal.</p>"))
        else:
            self._send(_home())


def main():
    port = int(os.environ.get("FORGECAD_UI_PORT", "8765"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"ForgeCAD test UI running at http://127.0.0.1:{port}/  (Ctrl+C to stop)")
    print("Pipeline progress will stream to THIS terminal.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down.")
        srv.shutdown()


if __name__ == "__main__":
    main()
