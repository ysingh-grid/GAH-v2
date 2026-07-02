"""
ui_server.py — the single-page LOCAL UI for ForgeCAD.

One screen, end to end: type a prompt (+ optional reference image) -> answer the clarifying
questions -> run -> watch it live and see EVERYTHING in one place: the build/verify timeline, the
exact code the agent ran (so you can read the PLANS and the CadQuery code), the build-verdict table,
the rendered multi-view images, and a final panel with the full plan JSON + extracted CadQuery code
+ STL/STEP downloads.

Run modes:
  * direct (default): runs orchestrator.run_pipeline in a background thread (proven path).
  * temporal (opt-in checkbox / FORGECAD_UI_TEMPORAL=1): submits a durable ForgeCADRunWorkflow to a
    local Temporal dev server + worker, and links the Temporal Web UI. Falls back to direct if
    temporalio isn't installed or the server isn't reachable.

SECURITY: this is a LOCAL tool — it binds 127.0.0.1 only and has NO authentication. The file-serving
endpoints reject path traversal and only serve from renders/ and exports/ inside the repo. Do not
expose it to a network without adding auth.

Pure standard library. Single run at a time (testing/demo tool).
"""

import atexit
import cgi
import html
import json
import mimetypes
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
REFS = ROOT / "refs"; REFS.mkdir(exist_ok=True)
LOGS = ROOT / "logs"
RENDERS = ROOT / "renders"
EXPORTS = ROOT / "exports"

import orchestrator  # noqa: E402
try:
    import plan_store  # noqa: E402
except Exception:
    plan_store = None

_RUN = {"status": "idle", "result": None, "error": None, "prompt": None,
        "log": [], "start_ts": 0.0, "mode": "direct", "workflow_id": None}
_LOCK = threading.Lock()


def _safe_label(label: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (label or "plan"))[:60]


# ----------------------------------------------------------------- live log capture
class _Tee:
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
    try:
        cands = [p for p in LOGS.glob("geometry_planning_*.jsonl")
                 if p.stat().st_mtime >= (since_ts - 2)]
        return max(cands, key=lambda p: p.stat().st_mtime) if cands else None
    except Exception:
        return None


def _parse_steps(log_file):
    """Return [{step, event_type, code, output, hasError, depth}] from the run's JSONL log."""
    steps = []
    if not log_file:
        return steps
    try:
        for line in open(log_file, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            steps.append({"step": e.get("step"), "event_type": e.get("event_type"),
                          "code": e.get("code") or "", "output": e.get("output") or "",
                          "hasError": e.get("hasError"), "depth": int(e.get("depth", 0) or 0)})
    except Exception:
        return steps
    return steps


def _build_table(steps):
    """Compact per-build-verify table: (step, verdict, failing_checks, token_minted)."""
    rows = []
    import re
    vre = re.compile(r'"verdict"\s*:\s*"(PASS|FAIL)"')
    fre = re.compile(r'"name"\s*:\s*"([a-z_]+)"\s*,\s*"passed"\s*:\s*false')
    tre = re.compile(r'"verification_token"\s*:\s*"[0-9a-f]{16,}"')
    for s in steps:
        out = s["output"]
        m = vre.search(out)
        if not m:
            continue
        failing = sorted(set(fre.findall(out)))
        tok = bool(tre.search(out)) or ("TOKEN ISSUED" in out)
        rows.append((s["step"], m.group(1), failing, tok))
    return rows


def _recent_renders(since_ts, limit=6):
    try:
        cands = [p for p in list(RENDERS.glob("solid-*.png")) + list(RENDERS.glob("output_*.png"))
                 if p.stat().st_mtime >= (since_ts - 2)]
        cands.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return cands[:limit]
    except Exception:
        return []


# ----------------------------------------------------------------- Temporal glue (optional)
def _temporal_available():
    try:
        import temporalio  # noqa: F401
        return True
    except Exception:
        return False


def _start_temporal(prompt, qa, image_path):
    """Start ForgeCADRunWorkflow; return workflow_id, or None so the caller falls back to direct."""
    if not _temporal_available():
        return None
    import asyncio
    from temporalio.client import Client
    addr = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    tq = os.environ.get("TEMPORAL_TASK_QUEUE", "forgecad")
    ns = os.environ.get("TEMPORAL_NAMESPACE", "default")
    wid = f"forgecad-ui-{int(time.time())}"

    async def _go():
        client = await Client.connect(addr, namespace=ns)
        await client.start_workflow(
            "ForgeCADRunWorkflow",
            {"prompt": prompt, "clarifications": qa,
             "reference_image_path": image_path or None, "clarify": False},
            id=wid, task_queue=tq)
        return wid

    try:
        return asyncio.run(_go())
    except Exception as e:
        print(f"[ui] temporal start failed ({e}); falling back to direct run.")
        return None


# ----------------------------------------------------------------- HTML
def _config():
    return orchestrator.load_run_config()


def _info(tip: str) -> str:
    """A small circular (i) tooltip: shows `tip` on hover/focus. Accessible (tabindex)."""
    return f'<span class="info" tabindex="0" data-tip="{html.escape(tip)}">i</span>'


def _temporal_reachable() -> bool:
    """Fast, fail-open TCP probe of the Temporal server (default localhost:7233). Never hangs."""
    addr = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    try:
        host, _, port = addr.partition(":")
        with socket.create_connection((host or "localhost", int(port or "7233")), timeout=0.25):
            return True
    except Exception:
        return False


# ---- Temporal lifecycle MANAGED BY THE UI (no manual commands) ---------------------------------
_TPROCS = {"server": None, "worker": None}   # subprocess.Popen handles
_TLOCK = threading.Lock()


def _temporal_cli_installed() -> bool:
    return shutil.which("temporal") is not None


def _worker_alive() -> bool:
    p = _TPROCS.get("worker")
    return p is not None and p.poll() is None


def _server_proc_alive() -> bool:
    p = _TPROCS.get("server")
    return p is not None and p.poll() is None


def _temporal_status() -> dict:
    return {"cli": _temporal_cli_installed(), "sdk": _temporal_available(),
            "server_reachable": _temporal_reachable(), "worker_alive": _worker_alive()}


def _start_temporal_stack():
    """Bring up the dev server + worker as managed subprocesses. Returns (ok, message). Robust:
    never double-starts; surfaces clear guidance if the CLI/SDK are missing."""
    with _TLOCK:
        if not _temporal_cli_installed():
            return (False, "Temporal CLI not installed. Install it (separate from the pip SDK): "
                           "`brew install temporal` (or curl -sSf https://temporal.download/cli.sh | sh).")
        if not _temporal_available():
            return (False, "temporalio SDK missing — `pip install -r temporal_harness/requirements.txt`.")
        try:
            LOGS.mkdir(exist_ok=True)
            # server
            if not _temporal_reachable() and not _server_proc_alive():
                slog = open(LOGS / "temporal_server.log", "ab")
                _TPROCS["server"] = subprocess.Popen(
                    ["temporal", "server", "start-dev"], cwd=str(ROOT), stdout=slog, stderr=slog)
                for _ in range(24):           # up to ~12s
                    if _temporal_reachable():
                        break
                    time.sleep(0.5)
                if not _temporal_reachable():
                    return (False, "Temporal server did not come up — see logs/temporal_server.log.")
            # worker
            if not _worker_alive():
                wlog = open(LOGS / "temporal_worker.log", "ab")
                env = {**os.environ, "PYTHONPATH": str(ROOT)}
                _TPROCS["worker"] = subprocess.Popen(
                    [sys.executable, "-m", "temporal_harness.worker"], cwd=str(ROOT),
                    env=env, stdout=wlog, stderr=wlog)
                time.sleep(2.0)
                if _TPROCS["worker"].poll() is not None:
                    return (False, "Worker exited immediately — see logs/temporal_worker.log.")
            return (True, "Temporal is up (server + worker).")
        except Exception as e:
            return (False, f"could not start Temporal: {type(e).__name__}: {e}")


def _stop_temporal_stack():
    """Terminate the worker then the server (fail-open). Called on /temporal/stop and at UI exit."""
    with _TLOCK:
        for key in ("worker", "server"):
            p = _TPROCS.get(key)
            if p is not None and p.poll() is None:
                try:
                    p.terminate()
                    p.wait(timeout=5)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass
            _TPROCS[key] = None


atexit.register(_stop_temporal_stack)


def _tail(path, n=40):
    try:
        if path.exists():
            return "".join(path.read_text(errors="replace").splitlines(keepends=True)[-n:])
    except Exception:
        pass
    return ""


_NAV_ITEMS = [
    ("/", "New run", "Start a fresh design: prompt -> clarify -> run."),
    ("/runs", "Runs", "Browse every past run and open its full inner-loop detail (plans, CadQuery "
                      "code, build/verify verdicts, renders)."),
    ("/analytics", "Analytics", "Aggregate dashboard: accepted vs best-effort, top failing checks, "
                                "trend over time."),
    ("/temporal", "Temporal", "Start/stop the durable Temporal server + worker right here — no "
                              "terminal commands."),
    ("http://localhost:8233", "Temporal Dashboard \u2197", "Opens Temporal's own Web UI "
        "(localhost:8233) to inspect the durable workflow timeline."),
]


def _nav() -> str:
    """Sticky top navigation on every page: New run / Runs / Analytics / Temporal (control) /
    Temporal Dashboard — each with an (i) tooltip — plus a live Temporal status badge."""
    items = []
    for href, label, tip in _NAV_ITEMS:
        ext = ' target="_blank" rel="noopener"' if href.startswith("http") else ""
        items.append(f'<a class="btn" href="{href}"{ext}>{label}</a>{_info(tip)}')
    if _temporal_reachable():
        badge = '<span class="badge on">Temporal: on</span>'
    else:
        badge = ('<span class="badge off">Temporal: off</span>'
                 + _info("Temporal is not running. Click the Temporal button to start it in one "
                         "click (needs the `temporal` CLI installed). Until then, runs use direct mode."))
    return '<div class="nav">' + "".join(items) + '<span class="spacer"></span>' + badge + '</div>'


def _page(body: str) -> bytes:
    return (f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>ForgeCAD</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
  :root {{
    --bg: #0f172a; --surface: #1e293b; --surface-hover: #334155;
    --text: #f8fafc; --text-muted: #94a3b8;
    --primary: #3b82f6; --primary-hover: #2563eb;
    --success: #10b981; --danger: #ef4444; --border: #334155; --radius: 12px;
  }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: 'Inter', system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 0; line-height: 1.6; min-height: 100vh; }}
  .container {{ max-width: 1000px; margin: 0 auto; padding: 24px; padding-bottom: 60px; }}
  h1 {{ font-size: 28px; font-weight: 700; margin-bottom: 16px; letter-spacing: -0.5px; margin-top: 0; }}
  h2 {{ font-size: 20px; font-weight: 600; margin-top: 32px; margin-bottom: 16px; color: #e2e8f0; }}
  p {{ margin-bottom: 16px; }}
  label {{ display: block; margin: 16px 0 8px; font-weight: 500; font-size: 14px; color: #cbd5e1; }}
  textarea, input[type=text] {{ width: 100%; padding: 12px 16px; background: #0f172a; border: 1px solid var(--border); border-radius: var(--radius); color: var(--text); font-size: 15px; font-family: inherit; transition: all 0.2s ease; }}
  textarea:focus, input[type=text]:focus {{ outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2); }}
  button, .action-btn {{ background: var(--primary); color: white !important; border: none; padding: 12px 24px; border-radius: var(--radius); font-size: 15px; font-weight: 600; cursor: pointer; transition: all 0.2s ease; margin-top: 16px; display: inline-flex; align-items: center; justify-content: center; gap: 8px; text-decoration: none; }}
  button:hover, .action-btn:hover {{ background: var(--primary-hover); transform: translateY(-1px); text-decoration: none; }}
  button:active, .action-btn:active {{ transform: translateY(0); }}
  .q {{ background: var(--surface); padding: 16px; border-radius: var(--radius); margin: 12px 0; border: 1px solid var(--border); }}
  .note {{ color: var(--text-muted); font-size: 14px; }}
  .ok {{ color: var(--success); }}
  .err {{ color: var(--danger); white-space: pre-wrap; }}
  .banner {{ padding: 12px 16px; border-radius: var(--radius); margin: 16px 0; font-size: 14px; font-weight: 500; display: flex; align-items: center; gap: 8px; }}
  .banner.t {{ background: rgba(59, 130, 246, 0.1); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.2); }}
  .banner.d {{ background: var(--surface); color: var(--text-muted); border: 1px solid var(--border); }}
  code {{ background: rgba(255, 255, 255, 0.1); padding: 2px 6px; border-radius: 4px; font-family: ui-monospace, monospace; font-size: 13px; }}
  .tablewrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; background: var(--surface); border-radius: var(--radius); border: 1px solid var(--border); margin: 16px 0; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
  td, th {{ padding: 12px 16px; text-align: left; border-bottom: 1px solid var(--border); }}
  th {{ background: rgba(0, 0, 0, 0.2); font-weight: 600; color: #cbd5e1; }}
  tr:last-child td {{ border-bottom: none; }}
  .box {{ background: #000; color: #d6d6d6; padding: 16px; border-radius: var(--radius); max-height: 400px; overflow: auto; font-size: 13px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; border: 1px solid var(--border); }}
  details {{ margin: 8px 0; background: var(--surface); border-radius: var(--radius); border: 1px solid var(--border); overflow: hidden; }}
  summary {{ cursor: pointer; font-size: 14px; font-weight: 600; padding: 12px 16px; background: rgba(0, 0, 0, 0.1); }}
  summary:hover {{ background: rgba(255, 255, 255, 0.05); }}
  details > pre, details > .box {{ margin: 0; border: none; border-radius: 0; border-top: 1px solid var(--border); }}
  img {{ max-width: 100%; border-radius: 8px; }}
  .imgs {{ display: flex; flex-wrap: wrap; gap: 12px; }}
  .imgs img {{ max-width: 320px; border: 1px solid var(--border); border-radius: 8px; object-fit: cover; transition: transform 0.2s; }}
  .imgs img:hover {{ transform: scale(1.02); }}
  pre {{ background: #000; border: 1px solid var(--border); padding: 16px; border-radius: var(--radius); max-height: 400px; overflow: auto; font-size: 13px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; color: #e2e8f0; }}
  .nav {{ position: sticky; top: 0; background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); display: flex; flex-wrap: wrap; gap: 12px; align-items: center; padding: 16px 24px; border-bottom: 1px solid var(--border); margin-bottom: 24px; z-index: 30; }}
  .nav a.btn {{ text-decoration: none; background: var(--surface); color: var(--text); padding: 8px 16px; border-radius: 99px; font-size: 14px; font-weight: 500; border: 1px solid var(--border); transition: all 0.2s ease; }}
  .nav a.btn:hover {{ background: var(--surface-hover); border-color: #475569; }}
  .handoff-btn {{ background: linear-gradient(135deg, #8b5cf6, #3b82f6) !important; color: white !important; border: none !important; box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3); margin-top: 8px; }}
  .handoff-btn:hover {{ box-shadow: 0 6px 16px rgba(59, 130, 246, 0.4) !important; transform: translateY(-1px) !important; }}
  .badge {{ font-size: 12px; padding: 4px 10px; border-radius: 999px; font-weight: 600; letter-spacing: 0.5px; text-transform: uppercase; }}
  .badge.on {{ background: rgba(16, 185, 129, 0.1); color: var(--success); border: 1px solid rgba(16, 185, 129, 0.2); }}
  .badge.off {{ background: rgba(148, 163, 184, 0.1); color: var(--text-muted); border: 1px solid rgba(148, 163, 184, 0.2); }}
  .spacer {{ flex: 1; }}
  .info {{ display: inline-flex; justify-content: center; align-items: center; width: 18px; height: 18px; border-radius: 50%; background: var(--border); color: var(--text-muted); font-size: 11px; font-weight: 700; cursor: help; position: relative; margin-left: 6px; }}
  .info:hover::after, .info:focus::after {{ content: attr(data-tip); position: absolute; left: 24px; top: -10px; width: 280px; background: #000; color: #fff; padding: 12px; border-radius: 8px; font-size: 13px; font-weight: 400; z-index: 40; line-height: 1.5; box-shadow: 0 4px 20px rgba(0,0,0,0.5); border: 1px solid var(--border); text-align: left; }}
  a {{ color: var(--primary); text-decoration: none; transition: color 0.2s; }}
  a:hover {{ color: #60a5fa; text-decoration: underline; }}
  @media(max-width:600px) {{ .imgs img {{ max-width: 100%; }} .container {{ padding: 16px; }} }}
</style></head><body>{_nav()}<div class="container">{body}</div></body></html>""").encode("utf-8")


def _home() -> bytes:
    return _page("""
<h1>ForgeCAD</h1>
<p class="note">Local tool (127.0.0.1, no auth). Type a request, optionally upload a reference image,
then answer a few clarifying questions and run. You'll see the full build, the plans, the CadQuery
code, and the renders here.</p>
<form method="POST" action="/clarify" enctype="multipart/form-data">
  <label>Design prompt """ + _info("Describe the object in plain words. e.g. 'design a centrifugal "
        "compressor impeller' or 'a 1-litre water bottle with a cap'.") + """</label>
  <textarea name="prompt" placeholder="e.g. design a centrifugal compressor impeller"></textarea>
  <label>Reference image (optional) """ + _info("Optional. Upload a photo/sketch of the target; the "
        "design is reviewed against it. e.g. a photo of an impeller.") + """</label>
  <input type="file" name="image" accept="image/*">
  <button type="submit">Get clarifying questions &rarr;</button>
</form>""")


def _clarify_page(prompt: str, image_path: str, questions: list) -> bytes:
    if questions:
        qrows = ('<p class="note">Answer these ' + _info("Answer the non-negotiables (size, count of "
                 "the main feature, orientation/mounting). Unsure? type 'use standard defaults'.")
                 + "</p>")
        for i, q in enumerate(questions):
            qrows += (f'<div class="q"><label>{html.escape(q)}</label>'
                      f'<input type="hidden" name="q_{i}" value="{html.escape(q)}">'
                      f'<input type="text" name="a_{i}" placeholder="your answer (or: use standard defaults)"></div>')
    else:
        qrows = '<p class="note">No clarifying questions — the request is well specified.</p>'
    img_note = (f'<p class="note ok">reference image: <code>{html.escape(image_path)}</code></p>'
                if image_path else '<p class="note">no image — proceeding from the text description.</p>')
    tnote = ("" if _temporal_available() else
             " <span class='note'>(temporalio not installed — will run directly)</span>")
    tchecked = " checked" if _temporal_reachable() else ""
    return _page(f"""
<h1>Clarify, then run</h1>
<p><b>Prompt:</b> {html.escape(prompt)}</p>{img_note}
<form method="POST" action="/run">
  <input type="hidden" name="prompt" value="{html.escape(prompt)}">
  <input type="hidden" name="image_path" value="{html.escape(image_path or '')}">
  <input type="hidden" name="n" value="{len(questions)}">
  {qrows}
  <label><input type="checkbox" name="use_temporal" value="1"{tchecked}> Durable run via Temporal
    {_info("Runs the job as a durable Temporal workflow (survives crashes; visible in the Temporal "
           "dashboard). Needs the dev server + worker; otherwise it falls back to a direct run.")}
    {tnote}</label>
  <button type="submit">Run pipeline &#9654;</button>
</form>
<p class="note"><a href="/status">status</a></p>""")


def _final_panel(result):
    """Final plan JSON + extracted CadQuery code + downloads + final render."""
    parts = []
    plan = None
    if plan_store is not None:
        try:
            plan = plan_store.load_plan("latest")
        except Exception:
            plan = None
    if isinstance(plan, dict):
        parts.append("<h2>Final plan</h2><pre>" + html.escape(json.dumps(plan, indent=2)[:12000]) + "</pre>")
        code = "\n\n# ---- next custom step ----\n".join(
            s.get("parameters", {}).get("code_sketch", "")
            for s in (plan.get("primitives_sequence") or [])
            if s.get("primitive_type") == "custom" and s.get("parameters", {}).get("code_sketch"))
        if code.strip():
            parts.append("<h2>CadQuery code (custom steps)</h2><pre>" + html.escape(code) + "</pre>")
        else:
            parts.append("<p class='note'>No custom CadQuery code — built entirely from certified "
                         "primitives / contour builders.</p>")
        # downloads
        title = plan.get("title")
        if title:
            safe = _safe_label(title)
            links = []
            for stem in (f"output_{safe}", f"besteffort_{safe}"):
                for ext in (".stl", ".step"):
                    fp = EXPORTS / f"{stem}{ext}"
                    if fp.exists():
                        rel = urllib.parse.quote(f"exports/{stem}{ext}")
                        links.append(f'<a href="/download?path={rel}">{stem}{ext}</a>')
            if links:
                forgecad_url = os.environ.get("FORGECAD_STUDIO_URL", "http://localhost:4000")
                parts.append("<h2>Download & Handoff</h2><p>" + " &nbsp; ".join(links) + "</p>")
                parts.append(f'<p><a href="{forgecad_url}" target="_blank" class="action-btn handoff-btn">🚀 Open in ForgeCAD Studio &nearr;</a></p>')
    return "\n".join(parts)


def _status_page() -> bytes:
    with _LOCK:
        st = dict(_RUN)
        narrative = list(_RUN["log"])[-120:]
        start_ts = _RUN["start_ts"]
    refresh = "<meta http-equiv='refresh' content='3'>" if st["status"] == "running" else ""
    body = f"{refresh}<h1>Status: {html.escape(st['status'])}</h1>"
    body += f"<p class='note'>prompt: {html.escape(str(st.get('prompt')))}</p>"

    # mode banner
    if st.get("mode", "").startswith("temporal") and st.get("workflow_id"):
        wid = html.escape(st["workflow_id"])
        link = f"http://localhost:8233/namespaces/default/workflows/{wid}"
        body += (f"<div class='banner t'>Durable run via <b>Temporal</b> — workflow <code>{wid}</code> "
                 f"&middot; <a href='{link}' target='_blank'>Open in Temporal Web UI &nearr;</a></div>")
    else:
        body += f"<div class='banner d'>Run mode: {html.escape(str(st.get('mode', 'direct')))}</div>"

    steps = _parse_steps(_current_log_file(start_ts)) if start_ts else []

    # build-verdict table
    rows = _build_table(steps)
    if rows:
        body += "<h2>Build / verify iterations</h2><table><tr><th>step</th><th>verdict</th>" \
                "<th>failing checks</th><th>token</th></tr>"
        for step, verdict, failing, tok in rows:
            cls = "ok" if verdict == "PASS" else "err"
            body += (f"<tr><td>{html.escape(str(step))}</td><td class='{cls}'>{verdict}</td>"
                     f"<td>{html.escape(', '.join(failing) or '-')}</td>"
                     f"<td>{'minted' if tok else '-'}</td></tr>")
        body += "</table>"

    # renders inline
    imgs = _recent_renders(start_ts) if start_ts else []
    if imgs:
        body += "<h2>Renders</h2><div class='imgs'>"
        for p in imgs:
            rel = urllib.parse.quote(f"renders/{p.name}")
            body += f"<img src='/render?path={rel}' alt='{html.escape(p.name)}'>"
        body += "</div>"

    # per-step code (plans + cadquery code as the agent wrote them)
    code_steps = [s for s in steps if s["event_type"] in ("execution_result", "code_generated")
                  and s["step"] not in (0, None) and s["code"].strip()]
    if code_steps:
        body += "<h2>What the AI did (code per step — plans &amp; CadQuery)</h2>"
        for s in code_steps[-40:]:
            head = next((c for c in s["code"].splitlines() if c.strip() and not c.strip().startswith("#")),
                        "step")
            err = " !!" if s.get("hasError") else ""
            body += (f"<details><summary>step {html.escape(str(s['step']))}: "
                     f"{html.escape(head.strip()[:90])}{err}</summary><pre>"
                     + html.escape(s["code"][:6000]) + "</pre></details>")

    if st["status"] == "done" and st["result"]:
        r = st["result"]
        body += (f"<h2 class='ok'>Done</h2><p class='ok'>Verdict: {html.escape(str(r.get('verdict')))} | "
                 f"Trust: {html.escape(str(r.get('trust_tier')))} | Title: {html.escape(str(r.get('title')))}</p>")
        try:
            body += _final_panel(r)
        except Exception as e:
            body += f"<p class='note'>(final panel unavailable: {html.escape(str(e))})</p>"
    elif st["status"] == "failed":
        body += f"<p class='err'>FAILED: {html.escape(str(st.get('error')))}</p>"
        try:
            body += _final_panel(None)   # a best-effort artifact may still exist
        except Exception:
            pass

    if narrative:
        body += "<h2>Pipeline log</h2><pre class='box'>" + html.escape("\n".join(narrative)) + "</pre>"
    if st["status"] == "running":
        body += "<p class='note'>Running &mdash; auto-refreshes every 3s.</p>"
    body += '<p><a href="/">&larr; new run</a></p>'
    return _page(body)


# ----------------------------------------------------------------- run drivers
def _runs_page() -> bytes:
    try:
        from temporal_harness import trace_store
        conn = trace_store.connect()
        rows = list(reversed(trace_store.all_runs(conn)))
    except Exception as e:
        return _page(f"<h1>Runs</h1><p class='note'>trace store unavailable: {html.escape(str(e))}</p>")
    if not rows:
        return _page("<h1>Runs</h1><p class='note'>No runs recorded yet — start one from "
                     "<a href='/'>New run</a>, or backfill history with "
                     "<code>python -m temporal_harness.ingest</code>.</p>")
    hdr = ("<h1>Runs " + _info("Every run ForgeCAD has done — click one to see its full inner loop: "
           "the plans, the CadQuery code, every build/verify verdict, and the renders.") + "</h1>")
    out = [hdr, "<div class='tablewrap'><table><tr><th>when</th><th>prompt</th><th>title</th>"
           "<th>outcome</th><th>trust</th><th>iters</th><th>tokens</th></tr>"]
    for r in rows:
        oc = r.get("outcome") or "?"
        cls = "ok" if oc == "accepted" else ("err" if oc == "besteffort" else "note")
        toks = (r.get("prompt_tokens") or 0) + (r.get("completion_tokens") or 0)
        rid = urllib.parse.quote(str(r.get("run_id") or ""))
        title = html.escape(str(r.get("title") or "(untitled)"))
        out.append(f"<tr><td>{html.escape(str(r.get('started_at') or '')[:19])}</td>"
                   f"<td>{html.escape(str(r.get('prompt') or '')[:60])}</td>"
                   f"<td><a href='/run_detail?run_id={rid}'>{title}</a></td>"
                   f"<td class='{cls}'>{html.escape(oc)}</td>"
                   f"<td>{html.escape(str(r.get('trust_tier') or '-'))}</td>"
                   f"<td>{html.escape(str(r.get('num_build_iterations') or 0))}</td>"
                   f"<td>{toks}</td></tr>")
    out.append("</table></div>")
    return _page("\n".join(out))


def _run_detail_page(run_id) -> bytes:
    try:
        from temporal_harness import trace_store
        conn = trace_store.connect()
        run = trace_store.get_run(conn, run_id)
        events = trace_store.events_for(conn, run_id)
        steps = trace_store.steps_for(conn, run_id)
    except Exception as e:
        return _page(f"<h1>Run</h1><p class='note'>trace store unavailable: {html.escape(str(e))}</p>")
    if not run:
        return _page(f"<h1>Run</h1><p class='err'>no run {html.escape(str(run_id))}</p>"
                     "<p><a href='/runs'>&larr; all runs</a></p>")
    rid = urllib.parse.quote(str(run_id))
    b = [f"<h1>{html.escape(str(run.get('title') or 'Run'))}</h1>"]

    # ---- 1. Summary ---------------------------------------------------------
    toks = (run.get("prompt_tokens") or 0) + (run.get("completion_tokens") or 0)
    b.append("<h2>Summary " + _info("The headline result of this run: what was asked, the final "
             "verdict, the trust tier, how many build/verify iterations it took, and token spend.")
             + "</h2>")
    b.append(f"<p class='note'>prompt: {html.escape(str(run.get('prompt') or ''))}</p>")
    b.append(f"<p>outcome: <b>{html.escape(str(run.get('outcome')))}</b> &middot; trust: "
             f"{html.escape(str(run.get('trust_tier')))} &middot; verdict: "
             f"{html.escape(str(run.get('final_verdict')))} &middot; iters: "
             f"{html.escape(str(run.get('num_build_iterations')))} &middot; tokens: {toks} &middot; "
             f"duration: {html.escape(str(run.get('duration_s') or '-'))}s &middot; "
             f"kind: {html.escape(str(run.get('assembly_kind')))}</p>")
    eps = run.get("export_paths") or []
    if eps:
        links = []
        for ep in eps:
            name = os.path.basename(str(ep))
            rel = urllib.parse.quote(f"exports/{name}")
            links.append(f"<a href='/download?path={rel}'>{html.escape(name)}</a>")
        b.append("<p>Download model: " + " &nbsp; ".join(links) + "</p>")

    # ---- 2. Renders ---------------------------------------------------------
    title = run.get("title")
    if title:
        safe = _safe_label(title)
        imgs = [RENDERS / f"{stem}.png" for stem in (f"output_{safe}", f"besteffort_{safe}")
                if (RENDERS / f"{stem}.png").exists()]
        if imgs:
            b.append("<h2>Render</h2><div class='imgs'>")
            for fp in imgs:
                rel = urllib.parse.quote(f"renders/{fp.name}")
                b.append(f"<img src='/render?path={rel}'>")
            b.append("</div>")

    # ---- 3. ForgeCAD handoff (exact parametric JSON + exact CadQuery) -------
    code = run.get("cadquery_code")
    hjson = run.get("handoff_json")
    b.append("<h2>ForgeCAD handoff " + _info("The exact, parametric handoff for downstream CAD: a "
             "forgecad.handoff.v1 JSON (every operation, parameter or custom code, pattern, and the "
             "EXACT resolved placement from the kernel build trace, plus the verification token) and "
             "a runnable CadQuery .py. The STEP export is the exact B-rep handoff.") + "</h2>")
    forgecad_url = os.environ.get("FORGECAD_STUDIO_URL", "http://localhost:4000")
    b.append("<p>"
             f"<a href='/handoff?run_id={rid}'>&#11015; Download .handoff.json</a> &nbsp; "
             f"<a href='/cqscript?run_id={rid}'>&#11015; Download .py (CadQuery)</a>"
             "</p>")
    b.append(f'<p><a href="{forgecad_url}" target="_blank" class="action-btn handoff-btn">🚀 Open in ForgeCAD Studio &nearr;</a></p>')
    if hjson and str(hjson).strip():
        b.append("<details><summary>handoff JSON (forgecad.handoff.v1)</summary><pre class='box'>"
                 + html.escape(str(hjson)[:40000]) + "</pre></details>")
    if code and str(code).strip():
        b.append("<details open><summary>CadQuery script</summary><pre class='box'>"
                 + html.escape(str(code)[:40000]) + "</pre></details>")
    else:
        b.append("<p class='note'>No CadQuery script stored for this run "
                 "(the .handoff.json above can still be generated on demand).</p>")

    # ---- 4. Final plan ------------------------------------------------------
    plan = run.get("plan_json")
    if isinstance(plan, dict):
        b.append("<h2>Final plan " + _info("The authoritative GeometryPlan the kernel built — the "
                 "geometry source of truth (the CadQuery above is reconstructed from this).")
                 + "</h2>")
        b.append("<details><summary>show plan JSON</summary><pre>"
                 + html.escape(json.dumps(plan, indent=2)[:40000]) + "</pre></details>")

    # ---- 5. Build / verify iterations --------------------------------------
    if events:
        b.append("<h2>Build / verify iterations " + _info("Each time the agent called the kernel: "
                 "the verdict, which checks failed, the advisory fidelity status, and whether a "
                 "token was minted.") + "</h2><div class='tablewrap'><table>"
                 "<tr><th>step</th><th>verdict</th><th>failing checks</th><th>fidelity</th>"
                 "<th>token</th><th>render</th></tr>")
        for e in events:
            v = e.get("verdict") or "?"
            cls = "ok" if v == "PASS" else "err"
            fc = ", ".join(e.get("failing_checks") or []) or "-"
            thumb = "-"
            png = e.get("png")
            if png:
                name = os.path.basename(str(png))
                if (RENDERS / name).exists():
                    rel = urllib.parse.quote(f"renders/{name}")
                    thumb = f"<a href='/render?path={rel}' target='_blank'>view</a>"
            b.append(f"<tr><td>{html.escape(str(e.get('step')))}</td><td class='{cls}'>{v}</td>"
                     f"<td>{html.escape(fc)}</td><td>{html.escape(str(e.get('fidelity_status') or '-'))}</td>"
                     f"<td>{'minted' if e.get('token_minted') else '-'}</td><td>{thumb}</td></tr>")
        b.append("</table></div>")

    # ---- 6. Tool-call timeline (RLM under the hood) -------------------------
    tool_rows = []
    for s in steps:
        for t in (s.get("tools") or []):
            verdict = s.get("verdict") if str(t).endswith("build_verify_render") else None
            tool_rows.append((s.get("step"), s.get("ts"), t, verdict,
                              s.get("llm_ms"), s.get("exec_ms")))
    if tool_rows:
        b.append("<h2>Tool-call timeline " + _info("Every MCP tool the RLM called, in order — which "
                 "tool, when, the verdict (for build/verify), and how long the LLM and the tool took. "
                 "This is the agent's behaviour under the hood.") + "</h2><div class='tablewrap'><table>"
                 "<tr><th>step</th><th>time</th><th>tool</th><th>verdict</th><th>llm ms</th>"
                 "<th>exec ms</th></tr>")
        for step, ts, tool, verdict, llm_ms, exec_ms in tool_rows:
            b.append(f"<tr><td>{html.escape(str(step))}</td>"
                     f"<td>{html.escape(str(ts or '')[11:19])}</td>"
                     f"<td>{html.escape(str(tool))}</td>"
                     f"<td>{html.escape(str(verdict or '-'))}</td>"
                     f"<td>{html.escape(str(llm_ms if llm_ms is not None else '-'))}</td>"
                     f"<td>{html.escape(str(exec_ms if exec_ms is not None else '-'))}</td></tr>")
        b.append("</table></div>")

    # ---- 7. Inner steps — full code + output + tokens + latency -------------
    if steps:
        b.append("<h2>Inner steps &mdash; full code, output, tokens, latency " + _info("The RLM's "
                 "complete per-step working: the exact code it generated (its decision/action, "
                 "including any CadQuery and its reasoning written as comments) and the response that "
                 "came back, with tokens and timing. Captured from the run log, not Temporal.")
                 + "</h2>")
        for s in steps:
            st_tok = (s.get("prompt_tokens") or 0) + (s.get("completion_tokens") or 0)
            tools = ", ".join(s.get("tools") or []) or "-"
            err = " !!ERROR" if s.get("has_error") else ""
            llm_ms = s.get("llm_ms")
            summ = (f"step {html.escape(str(s.get('step')))} &middot; {html.escape(tools)} &middot; "
                    f"{st_tok} tok &middot; {html.escape(str(llm_ms if llm_ms is not None else '-'))}ms"
                    f"{err}")
            body = "<pre>" + html.escape(str(s.get("code") or "")[:20000]) + "</pre>"
            outp = str(s.get("output") or "")
            if outp.strip():
                body += "<div class='note'>output / response:</div><pre>" + html.escape(outp[:20000]) + "</pre>"
            b.append(f"<details><summary>{summ}</summary>{body}</details>")
        b.append("<p class='note'>Note: the engine exposes no separate hidden chain-of-thought "
                 "(<code>reasoning_tokens=0</code>) — for this code-RLM, its \u201creasoning\u201d is "
                 "the code + comments it writes, which is shown above in full.</p>")
    else:
        # Fallback: parse the stored log directly if the steps table isn't populated.
        lf = run.get("log_file")
        if lf and os.path.exists(str(lf)):
            try:
                pstes = _parse_steps(lf)
                cs = [s for s in pstes if s["event_type"] in ("execution_result", "code_generated")
                      and s["step"] not in (0, None) and s["code"].strip()]
                if cs:
                    b.append("<h2>Inner steps &mdash; code per step</h2>")
                    for s in cs[-60:]:
                        head = next((c for c in s["code"].splitlines()
                                     if c.strip() and not c.strip().startswith("#")), "step")
                        err = " !!" if s.get("hasError") else ""
                        b.append(f"<details><summary>step {html.escape(str(s['step']))}: "
                                 f"{html.escape(head.strip()[:90])}{err}</summary><pre>"
                                 + html.escape(s["code"][:20000]) + "</pre></details>")
            except Exception:
                pass

    b.append("<p><a href='/runs'>&larr; all runs</a></p>")
    return _page("\n".join(b))


def _analytics_page() -> bytes:
    try:
        from temporal_harness import analytics, trace_store
        conn = trace_store.connect()
        rep = analytics.render_report(conn)
        s = analytics.summary(conn)
    except Exception as e:
        return _page(f"<h1>Analytics</h1><p class='note'>analytics unavailable: {html.escape(str(e))}</p>")
    badges = (f"<span class='badge on'>accepted {s.get('accepted')}</span> "
              f"<span class='badge off'>besteffort {s.get('besteffort')}</span> "
              f"<span class='badge off'>accepted_rate {s.get('accepted_rate')}</span>")
    return _page(f"<h1>Analytics</h1><p>{badges}</p><pre class='box'>" + html.escape(rep) + "</pre>")


def _temporal_page(msg: str = "") -> bytes:
    s = _temporal_status()

    def b(ok, on, off):
        return f"<span class='badge {'on' if ok else 'off'}'>{on if ok else off}</span>"

    up = s["server_reachable"] and s["worker_alive"]
    toggle = ('<form method="POST" action="/temporal/stop"><button type="submit">Stop Temporal</button></form>'
              if up else
              '<form method="POST" action="/temporal/start"><button type="submit">Start Temporal</button></form>')
    note = f"<p class='note'>{html.escape(msg)}</p>" if msg else ""
    if not s["cli"]:
        note += ("<p class='err'>The Temporal CLI is not installed (separate from the pip SDK). "
                 "Install it: <code>brew install temporal</code> "
                 "(or <code>curl -sSf https://temporal.download/cli.sh | sh</code>), then click Start.</p>")
    title_tip = _info("One-click start/stop of the durable Temporal server + worker. No terminal "
                      "commands needed (the CLI must be installed once).")
    badges = ("<p>" + b(s["cli"], "CLI installed", "CLI missing") + " "
              + b(s["sdk"], "SDK installed", "SDK missing") + " "
              + b(s["server_reachable"], "server reachable", "server down") + " "
              + b(s["worker_alive"], "worker running", "worker stopped") + "</p>")
    hint = ("<p class='note'>Starting can take a few seconds (the dev server boots, then the worker "
            "registers). When it's up, new runs go durable automatically and appear under "
            "<a href='/runs'>Runs</a>; inspect the workflow timeline in the "
            "<a href='http://localhost:8233' target='_blank' rel='noopener'>Temporal Web UI &nearr;</a>.</p>")
    body = "<h1>Temporal control " + title_tip + "</h1>" + note + badges + toggle + hint
    wt = _tail(LOGS / "temporal_worker.log")
    st = _tail(LOGS / "temporal_server.log")
    if wt:
        body += "<h2>worker log (tail)</h2><pre class='box'>" + html.escape(wt) + "</pre>"
    if st:
        body += "<h2>server log (tail)</h2><pre class='box'>" + html.escape(st) + "</pre>"
    return _page(body)


def _do_run(prompt, established_qa, image_path):
    with _LOCK:
        _RUN.update(status="running", result=None, error=None, prompt=prompt,
                    log=[], start_ts=time.time(), mode="direct", workflow_id=None)
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
        _ingest_quietly()   # fold this run into the trace store so it appears in /runs immediately


def _ingest_quietly():
    """Fold artifacts into the SQLite trace store. Fail-open: never raises into the run thread."""
    try:
        from temporal_harness import ingest
        ingest.ingest_all()
    except Exception:
        pass


def _watch_temporal(prompt, workflow_id):
    """Lightweight watcher for a Temporal run: the real work happens in the worker; the UI reads
    logs/renders/trace store. We just mark running and let /status reflect artifacts as they land."""
    with _LOCK:
        _RUN.update(status="running", result=None, error=None, prompt=prompt,
                    log=[f"[temporal] workflow {workflow_id} submitted; watch the Temporal Web UI."],
                    start_ts=time.time(), mode="temporal", workflow_id=workflow_id)
    # We do not block on the workflow result here (the http.server thread must stay responsive);
    # /status shows live artifacts. A future enhancement can poll the workflow handle for the result.


# ----------------------------------------------------------------- HTTP
def _safe_serve(handler, path_param, allowed_dir, attachment=False):
    """Serve a file ONLY if it resolves inside `allowed_dir` (reject path traversal)."""
    try:
        raw = urllib.parse.unquote(path_param or "")
        cand = (ROOT / raw) if not os.path.isabs(raw) else Path(raw)
        real = os.path.realpath(str(cand))
        base = os.path.realpath(str(allowed_dir))
        if not (real == base or real.startswith(base + os.sep)) or not os.path.isfile(real):
            handler._send(_page("<p class='err'>not found</p>"), code=404)
            return
        data = open(real, "rb").read()
        ctype = mimetypes.guess_type(real)[0] or "application/octet-stream"
        handler.send_response(200)
        handler.send_header("Content-Type", ctype)
        handler.send_header("Content-Length", str(len(data)))
        if attachment:
            handler.send_header("Content-Disposition",
                                f'attachment; filename="{os.path.basename(real)}"')
        handler.end_headers()
        handler.wfile.write(data)
    except Exception:
        try:
            handler._send(_page("<p class='err'>error</p>"), code=500)
        except Exception:
            pass


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: bytes, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass

    def _serve_cqscript(self, run_id):
        """Serve a run's whole-design CadQuery script as a .py download (guarded)."""
        try:
            from temporal_harness import trace_store
            conn = trace_store.connect()
            run = trace_store.get_run(conn, run_id)
            code = (run or {}).get("cadquery_code") or ""
            if not run or not str(code).strip():
                self._send(_page("<p class='err'>no CadQuery script for this run</p>"), code=404)
                return
            data = str(code).encode("utf-8")
            fname = (_safe_label(run.get("title") or "forgecad_design") or "design") + ".py"
            self.send_response(200)
            self.send_header("Content-Type", "text/x-python; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
            self.end_headers()
            self.wfile.write(data)
        except Exception:
            try:
                self._send(_page("<p class='err'>error</p>"), code=500)
            except Exception:
                pass

    def _serve_handoff(self, run_id):
        """Serve a run's forgecad.handoff.v1 JSON as a download; generate on demand (build the plan
        to get the exact trace) if it wasn't persisted. Guarded + fail-open."""
        try:
            from temporal_harness import trace_store
            conn = trace_store.connect()
            run = trace_store.get_run(conn, run_id)
            if not run:
                self._send(_page("<p class='err'>no such run</p>"), code=404)
                return
            payload = run.get("handoff_json")
            if not (payload and str(payload).strip()):
                plan = run.get("plan_json")
                if not isinstance(plan, dict):
                    self._send(_page("<p class='err'>no plan to build a handoff from</p>"), code=404)
                    return
                try:
                    from cad_kernel import kernel, handoff
                    res = kernel.build_plan(plan)
                    meta = res.get("meta") if res.get("ok") else None
                    payload = handoff.to_handoff_json(plan, meta=meta,
                                                      token=run.get("verification_token"),
                                                      measured_bbox=run.get("measured_bbox"))
                except Exception:
                    payload = None
            if not (payload and str(payload).strip()):
                self._send(_page("<p class='err'>could not produce a handoff</p>"), code=404)
                return
            data = str(payload).encode("utf-8")
            fname = (_safe_label(run.get("title") or "forgecad_design") or "design") + ".handoff.json"
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
            self.end_headers()
            self.wfile.write(data)
        except Exception:
            try:
                self._send(_page("<p class='err'>error</p>"), code=500)
            except Exception:
                pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/render":
            _safe_serve(self, (qs.get("path") or [""])[0], RENDERS)
        elif parsed.path == "/download":
            _safe_serve(self, (qs.get("path") or [""])[0], EXPORTS, attachment=True)
        elif parsed.path == "/runs":
            self._send(_runs_page())
        elif parsed.path == "/run_detail":
            self._send(_run_detail_page((qs.get("run_id") or [""])[0]))
        elif parsed.path == "/cqscript":
            self._serve_cqscript((qs.get("run_id") or [""])[0])
        elif parsed.path == "/handoff":
            self._serve_handoff((qs.get("run_id") or [""])[0])
        elif parsed.path == "/analytics":
            self._send(_analytics_page())
        elif parsed.path == "/temporal":
            self._send(_temporal_page())
        elif parsed.path.startswith("/status"):
            self._send(_status_page())
        else:
            self._send(_home())

    def do_POST(self):
        if self.path.startswith("/temporal/start"):
            ok, msg = _start_temporal_stack()
            self._send(_temporal_page(("OK — " if ok else "Could not start — ") + msg))
            return
        if self.path.startswith("/temporal/stop"):
            _stop_temporal_stack()
            self._send(_temporal_page("Temporal stopped."))
            return
        if self.path.startswith("/clarify"):
            fs = cgi.FieldStorage(fp=self.rfile, headers=self.headers,
                                  environ={"REQUEST_METHOD": "POST",
                                           "CONTENT_TYPE": self.headers.get("Content-Type", "")})
            prompt = (fs.getfirst("prompt") or "").strip()
            image_path = ""
            if "image" in fs and getattr(fs["image"], "filename", None):
                item = fs["image"]
                ext = os.path.splitext(item.filename)[1].lower() or ".png"
                if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                    ext = ".png"
                image_path = str(REFS / f"ref_{int(time.time())}{ext}")
                with open(image_path, "wb") as f:
                    f.write(item.file.read(8 * 1024 * 1024))  # cap upload at 8 MB
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
            length = int(self.headers.get("Content-Length", 0))
            data = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
            prompt = (data.get("prompt", [""])[0]).strip()
            image_path = (data.get("image_path", [""])[0]).strip()
            n = int(data.get("n", ["0"])[0] or 0)
            use_temporal = bool(data.get("use_temporal")) or os.environ.get("FORGECAD_UI_TEMPORAL") == "1"
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

            started_temporal = False
            if use_temporal:
                wid = _start_temporal(prompt, established_qa, image_path)
                if wid:
                    threading.Thread(target=_watch_temporal, args=(prompt, wid), daemon=True).start()
                    started_temporal = True
            if not started_temporal:
                if use_temporal:
                    with _LOCK:
                        _RUN["mode"] = "direct (temporal unavailable)"
                threading.Thread(target=_do_run, args=(prompt, established_qa, image_path),
                                 daemon=True).start()
            self._send(_page("<meta http-equiv='refresh' content='1;url=/status'>"
                             "<h1>Started &#9654;</h1><p>Opening the live view&hellip; "
                             "(<a href='/status'>/status</a>).</p>"))
        else:
            self._send(_home())


def main():
    port = int(os.environ.get("FORGECAD_UI_PORT", "8765"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"ForgeCAD UI running at http://127.0.0.1:{port}/  (local only; Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down.")
        srv.shutdown()
    finally:
        _stop_temporal_stack()   # clean up any Temporal server/worker the UI started


if __name__ == "__main__":
    main()
