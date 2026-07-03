/**
 * GAH-v2 Frontend — Dashboard UI with live agent trace.
 *
 * v0.3.1 — Fixed Temporal toggle (always clickable — it's the power switch).
 *          Structured trace viewer with accordion cards.
 *          Real health checks with server lifecycle awareness.
 */
(function () {
  'use strict';

  const BACKEND = window.BACKEND_URL || 'http://localhost:8001';
  const TEMPORAL_UI_URL = 'http://localhost:8233';
  const FORGECAD_URL = 'http://localhost:4000';

  const S = {
    designId: null,
    runId: null,
    ws: null,
    sending: false,
    activeView: 'new-run',
    useTemporal: false,
    useForgeCAD: false,
    backendOnline: false,
    temporalOnline: false,
    temporalStarting: false,
    forgecadOnline: false,
  };

  const el = id => document.getElementById(id);

  /* ─── Navigation ───────────────────────────────────────────────────────── */
  function showView(viewId) {
    S.activeView = viewId;
    document.querySelectorAll('.ga-view').forEach(v => v.style.display = 'none');
    document.querySelectorAll('.ga-nav-btn').forEach(b => b.classList.remove('active'));
    if (viewId === 'new-run') {
      const v = el('ga-new-run-view'); if (v) v.style.display = 'flex';
      document.querySelector('button[onclick*="new-run"]')?.classList.add('active');
    } else if (viewId === 'runs') {
      const v = el('ga-runs-view'); if (v) v.style.display = 'block';
      document.querySelector('button[onclick*="runs"]')?.classList.add('active');
      fetchRunHistory();
    } else if (viewId === 'studio') {
      const v = el('ga-studio-view'); if (v) v.style.display = 'flex';
    }
  }

  /* ─── Toasts ───────────────────────────────────────────────────────────── */
  function showWarning(msg) {
    const old = document.querySelector('.ga-toast'); if (old) old.remove();
    const t = document.createElement('div'); t.className = 'ga-toast'; t.textContent = '⚠ ' + msg;
    document.body.appendChild(t); setTimeout(() => { if (t.parentNode) t.remove(); }, 6000);
  }
  function showSuccess(msg) {
    const old = document.querySelector('.ga-toast'); if (old) old.remove();
    const t = document.createElement('div'); t.className = 'ga-toast ga-toast-success'; t.textContent = '✅ ' + msg;
    document.body.appendChild(t); setTimeout(() => { if (t.parentNode) t.remove(); }, 5000);
  }

  /* ─── Toggle — calls backend to start/stop Temporal ────────────────────── */
  function toggleTemporal(on) {
    if (S.temporalStarting) return;

    if (on) {
      S.temporalStarting = true;
      const desc = el('ga-temporal-desc'); if (desc) desc.textContent = 'Starting Temporal...';
      const chk = el('ga-temporal-check'); if (chk) chk.disabled = true;
      traceLog('🔄 Starting Temporal services...', 'meta');

      fetch(BACKEND + '/temporal/start', { method: 'POST' })
        .then(r => r.json())
        .then(status => {
          S.temporalStarting = false;
          if (status.server_up && status.worker_up) {
            S.temporalOnline = true; S.useTemporal = true;
            if (desc) desc.textContent = 'On — Temporal executor (live)';
            updateServiceDot('ga-temporal-status', 'online');
            _syncConfig();
            showSuccess('Temporal is ready — next run uses Temporal pipeline');
            traceLog('✅ Temporal running. Next run routes via Temporal.', 'success');
          } else if (status.server_up) {
            S.temporalOnline = true; S.useTemporal = true;
            if (desc) desc.textContent = 'On — server up, worker starting...';
            updateServiceDot('ga-temporal-status', 'online');
            _syncConfig();
            showWarning('Server up, worker still initializing.');
          } else {
            S.temporalOnline = false; S.useTemporal = false;
            if (desc) desc.textContent = 'Off — could not start';
            updateServiceDot('ga-temporal-status', 'offline');
            // Revert checkbox without re-triggering onchange
            if (chk) { chk.onchange = null; chk.checked = false; chk.onchange = function() { window.__gah.toggleTemporal(this.checked); }; chk.disabled = false; }
            showWarning('Could not start Temporal. Is temporal CLI installed?');
            traceLog('❌ Failed to start Temporal.', 'error');
          }
          _updateToggleRowState();
          if (chk) chk.disabled = false;
        })
        .catch(err => {
          S.temporalStarting = false; S.temporalOnline = false; S.useTemporal = false;
          if (desc) desc.textContent = 'Off — in-process executor';
          updateServiceDot('ga-temporal-status', 'offline');
          if (chk) { chk.onchange = null; chk.checked = false; chk.onchange = function() { window.__gah.toggleTemporal(this.checked); }; chk.disabled = false; }
          _updateToggleRowState();
          showWarning('Temporal start request failed. Check backend logs.');
          traceLog('❌ Temporal error: ' + err.message, 'error');
        });
    } else {
      S.useTemporal = false;
      const desc = el('ga-temporal-desc'); if (desc) desc.textContent = 'Off — stopping worker...';
      fetch(BACKEND + '/temporal/stop', { method: 'POST' })
        .then(r => r.json())
        .then(status => {
          S.temporalOnline = status.server_up && status.worker_up;
          if (desc) desc.textContent = 'Off — in-process executor';
          traceLog('Temporal worker stopped. In-process executor active.', 'meta');
          _syncConfig(); _updateToggleRowState(); healthCheck();
        })
        .catch(() => { if (desc) desc.textContent = 'Off — in-process executor'; _syncConfig(); _updateToggleRowState(); });
    }
  }

  function toggleForgeCAD(on) {
    if (on && !S.forgecadOnline) { showWarning('ForgeCAD Studio not reachable at localhost:4000.'); const c = el('ga-forgecad-check'); if (c) c.checked = false; return; }
    S.useForgeCAD = on;
    const desc = el('ga-forgecad-desc'); if (desc) desc.textContent = on ? 'On — auto-open Studio' : 'Off — download only';
    _syncConfig();
  }

  function _syncConfig() {
    if (!S.designId) return Promise.resolve();
    return fetch(BACKEND + '/designs/' + S.designId + '/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ use_temporal: S.useTemporal, use_forgecad: S.useForgeCAD }),
    }).catch(() => {});
  }

  /* ─── _updateToggleRowState — THE POWER SWITCH MUST ALWAYS BE CLICKABLE ── */
  function _updateToggleRowState() {
    const temporalRow = el('ga-temporal-toggle-row');
    const forgecadRow = el('ga-forgecad-toggle-row');
    const temporalChk = el('ga-temporal-check');
    const forgecadChk = el('ga-forgecad-check');

    // Temporal toggle: ALWAYS clickable. Health dot shows status; toggle controls it.
    if (temporalRow) {
      temporalRow.style.opacity = '1';
      temporalRow.style.pointerEvents = 'auto';
      temporalRow.title = S.temporalOnline
        ? 'Temporal running on localhost:7233' : S.temporalStarting ? 'Starting...' : 'Toggle ON to start Temporal';
    }
    // Only uncheck if fully offline AND checkbox is currently checked AND we're not starting
    if (temporalChk && !S.temporalOnline && !S.temporalStarting && temporalChk.checked) {
      temporalChk.onchange = null;
      temporalChk.checked = false;
      temporalChk.onchange = function() { window.__gah.toggleTemporal(this.checked); };
      S.useTemporal = false;
      const desc = el('ga-temporal-desc'); if (desc) desc.textContent = 'Off — in-process executor';
    }

    // ForgeCAD: keep disabled when offline (it's not a lifecycle toggle, it's an external service)
    if (forgecadRow) {
      forgecadRow.style.opacity = S.forgecadOnline ? '1' : '0.5';
      forgecadRow.style.pointerEvents = S.forgecadOnline ? 'auto' : 'none';
      forgecadRow.title = S.forgecadOnline ? 'ForgeCAD reachable' : 'ForgeCAD not running';
    }
    if (forgecadChk && !S.forgecadOnline) {
      forgecadChk.checked = false; S.useForgeCAD = false;
      const desc = el('ga-forgecad-desc'); if (desc) desc.textContent = 'Off — download only';
    }
  }

  /* ─── Health Checks ────────────────────────────────────────────────────── */
  function updateServiceDot(rowId, dotClass) {
    const row = el(rowId); if (!row) return;
    const dot = row.querySelector('.ga-status-dot'); if (!dot) return;
    dot.className = 'ga-status-dot ' + dotClass;
  }

  function healthCheck() {
    updateServiceDot('ga-backend-status', 'checking');
    fetch(BACKEND + '/health').then(r => r.json())
      .then(d => { S.backendOnline = d.status === 'ok'; updateServiceDot('ga-backend-status', S.backendOnline ? 'online' : 'offline'); })
      .catch(() => { S.backendOnline = false; updateServiceDot('ga-backend-status', 'offline'); });

    updateServiceDot('ga-temporal-status', 'checking');
    fetch(BACKEND + '/temporal/status').then(r => r.json())
      .then(st => { S.temporalOnline = st.server_up && st.worker_up; updateServiceDot('ga-temporal-status', S.temporalOnline ? 'online' : 'offline'); _updateToggleRowState(); })
      .catch(() => { S.temporalOnline = false; updateServiceDot('ga-temporal-status', 'offline'); _updateToggleRowState(); });

    updateServiceDot('ga-forgecad-status', 'checking');
    fetch(FORGECAD_URL, { mode: 'no-cors' }).then(() => { S.forgecadOnline = true; updateServiceDot('ga-forgecad-status', 'online'); })
      .catch(() => { S.forgecadOnline = false; updateServiceDot('ga-forgecad-status', 'offline'); });
    setTimeout(_updateToggleRowState, 500);
  }

  function openTemporal() {
    if (S.temporalOnline) { window.open(TEMPORAL_UI_URL, '_blank', 'noopener'); }
    else { showWarning('Temporal not running. Toggle the switch ON first.'); }
  }
  function openForgeCAD() {
    if (S.forgecadOnline) { window.open(FORGECAD_URL, '_blank', 'noopener'); }
    else { showWarning('ForgeCAD Studio not reachable at localhost:4000.'); }
  }

  /* ─── Live Trace ───────────────────────────────────────────────────────── */
  function traceLog(text, type) {
    const body = el('ga-trace-output'); if (!body) return;
    const line = document.createElement('div'); line.className = 'ga-trace-line ga-trace-' + (type || 'meta');
    line.textContent = text; body.appendChild(line); body.scrollTop = body.scrollHeight;
  }
  function clearTrace() { const body = el('ga-trace-output'); if (body) body.innerHTML = '<div class="ga-trace-line ga-trace-meta">System ready. Enter a design prompt to start.</div>'; }
  function setStatus(text) { const badge = el('ga-status-badge'); if (!badge) return; badge.textContent = text; badge.className = 'ga-status-badge ' + text.replace(/\s+/g, '-').toLowerCase(); }

  /* ─── Assistant ────────────────────────────────────────────────────────── */
  function showAssistant(html, showReply) {
    const box = el('ga-assistant-box'), area = el('ga-assistant-content'); if (!box || !area) return;
    box.style.display = 'block'; area.innerHTML = html;
    if (showReply) {
      const ta = document.createElement('textarea'); ta.className = 'ga-reply-input'; ta.placeholder = 'Type your clarification...';
      const btn = document.createElement('button'); btn.textContent = 'Submit'; btn.className = 'ga-btn-primary ga-btn-sm'; btn.style.width = 'auto';
      btn.onclick = () => { if (!ta.value.trim()) return; sendMsg(ta.value.trim()); box.style.display = 'none'; };
      area.appendChild(ta); area.appendChild(btn);
    }
  }
  function hideAssistant() { const box = el('ga-assistant-box'); if (box) box.style.display = 'none'; }

  /* ─── Reset ────────────────────────────────────────────────────────────── */
  function resetUI() {
    const inp = el('ga-input'); if (inp) { inp.value = ''; inp.disabled = false; }
    const fn = el('ga-file-name'); if (fn) fn.textContent = 'No file chosen';
    hideAssistant(); S.designId = null; S.runId = null;
    if (S.ws) { try { S.ws.close(); } catch (_) {} S.ws = null; }
    S.sending = false; const sendBtn = el('ga-send'); if (sendBtn) sendBtn.disabled = false;
    clearTrace(); setStatus('idle'); showView('new-run');
  }

  /* ─── Run History ──────────────────────────────────────────────────────── */
  function fetchRunHistory() {
    fetch(BACKEND + '/runs').then(r => r.json()).then(data => {
      const tbody = el('ga-runs-tbody'), empty = el('ga-runs-empty'), count = el('ga-runs-count');
      if (!tbody) return; if (count) count.textContent = data.length + ' runs';
      if (data.length === 0) { tbody.innerHTML = ''; if (empty) empty.style.display = 'block'; return; }
      if (empty) empty.style.display = 'none';
      tbody.innerHTML = data.map(run => {
        const rid = (run.run_id || '').substring(0, 14), prompt = (run.prompt || '').substring(0, 60);
        const status = run.status || 'unknown', ts = run.timestamp ? new Date(run.timestamp).toLocaleString() : '-';
        const bc = status === 'success' || status === 'done' ? 'success' : status === 'failed' ? 'failed' : 'thinking';
        let a = ''; if (run.has_trace) a += '<button class="ga-btn-secondary ga-btn-xs" onclick="window.__gah.viewTrace(\'' + run.run_id + '\')">📋</button>';
        if (run.has_stl) a += '<a href="' + BACKEND + '/runs/' + run.run_id + '/stl" class="ga-btn-secondary ga-btn-xs" download>⬇STL</a>';
        if (run.has_step) a += '<a href="' + BACKEND + '/runs/' + run.run_id + '/step" class="ga-btn-secondary ga-btn-xs" download>⬇STEP</a>';
        return '<tr><td style="font-family:var(--font-mono);font-size:11px;">' + rid + '…</td><td style="max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="' + _escAttr(run.prompt) + '">' + _escHtml(prompt) + '</td><td><span class="ga-status-badge ' + bc + '">' + status + '</span></td><td style="font-size:11px;color:var(--text-muted);">' + ts + '</td><td class="ga-actions-cell">' + a + '</td></tr>';
      }).join('');
    }).catch(() => { traceLog('Failed to load run history.', 'error'); });
  }

  /* ─── Structured Trace Viewer ──────────────────────────────────────────── */
  function viewTrace(runId) {
    fetch(BACKEND + '/runs/' + runId + '/trace').then(r => r.json()).then(data => {
      const modal = el('ga-trace-modal'), content = el('ga-trace-content');
      if (!modal || !content) return; content.innerHTML = renderStructuredTrace(data); modal.style.display = 'flex';
    }).catch(() => traceLog('Could not load trace.', 'error'));
  }
  function closeTrace() { const m = el('ga-trace-modal'); if (m) m.style.display = 'none'; }

  function renderStructuredTrace(trace) {
    if (!trace || typeof trace !== 'object') return '<p class="ga-text-muted">No trace data.</p>';
    const o = trace.outcome || {}, s = o.status || 'unknown'; let h = '';
    if (trace.prompt) h += _tcCard('📝','Prompt','info',false,'<div style="color:var(--text-main);font-size:13px;padding:4px 0;">'+_escHtml(trace.prompt)+'</div>');
    if (trace.plan) h += _tcCard('🧠','Plan','info',false,'<div class="ga-tc-json">'+_escHtml(JSON.stringify(trace.plan,null,2))+'</div>');
    if (trace.code) h += _tcCard('⚙️','CadQuery Code','info',false,'<div class="ga-tc-code">'+_escHtml(trace.code)+'</div>');
    const mesh = trace.mesh_report || {};
    if (Object.keys(mesh).length > 0) {
      let mh = '<div class="ga-tc-mesh-grid">';
      const fs = [{k:'watertight',l:'Watertight',f:v=>v?'✅ Yes':'❌ No'},{k:'manifold',l:'Manifold',f:v=>v?'✅ Yes':'❌ No'},{k:'volume',l:'Volume (mm³)',f:v=>typeof v==='number'?v.toFixed(0):String(v)},{k:'surface_area',l:'Surface (mm²)',f:v=>typeof v==='number'?v.toFixed(0):String(v)},{k:'num_faces',l:'Faces',f:v=>String(v)},{k:'num_vertices',l:'Vertices',f:v=>String(v)},{k:'num_triangles',l:'Triangles',f:v=>String(v)}];
      for (const f of fs) { const v=mesh[f.k]; if (v!==undefined&&v!==null) mh+='<div class="ga-tc-mesh-stat"><div class="stat-value">'+f.f(v)+'</div><div class="stat-label">'+f.l+'</div></div>'; }
      mh += '</div>'; h += _tcCard('📐','Mesh Report',mesh.watertight?'pass':'fail',false,mh);
    }
    const renders = trace.renders || {};
    if (Object.keys(renders).length > 0) {
      let rh = '<div class="ga-tc-renders">';
      for (const [view,url] of Object.entries(renders)) { if (typeof url==='string'&&url.startsWith('data:image')) rh+='<div class="ga-tc-render-thumb"><img src="'+url+'" alt="'+view+'" loading="lazy"><div class="render-label">'+_escHtml(view)+'</div></div>'; }
      rh += '</div>'; h += _tcCard('📸','Renders','info',false,rh);
    }
    const verdict = trace.verdict || {};
    if (Object.keys(verdict).length > 0) {
      let vh = ''; const sc = verdict.score ?? verdict.similarity; let pct = 0; if (typeof sc==='number') pct = Math.round(sc*100);
      if (pct>0||sc!==undefined) { const c = pct>=80?'var(--success)':pct>=50?'var(--warning)':'var(--danger)'; vh+='<div class="ga-tc-score-label">Match Score: '+pct+'%</div><div class="ga-tc-score-bar"><div class="ga-tc-score-fill" style="width:'+pct+'%;background:'+c+';"></div></div>'; }
      if (verdict.feedback||verdict.judge_comment) vh+='<div style="margin-top:8px;padding:10px;background:#F8FAFC;border-radius:6px;font-size:13px;">'+_escHtml(verdict.feedback||verdict.judge_comment||'')+'</div>';
      vh+='<details style="margin-top:8px;"><summary style="cursor:pointer;font-size:11px;color:var(--text-muted);">Raw JSON</summary><div class="ga-tc-json">'+_escHtml(JSON.stringify(verdict,null,2))+'</div></details>';
      h += _tcCard('🔍','Verifier Verdict',(verdict.passed||verdict.result==='pass'||pct>=80)?'pass':'fail',false,vh);
    }
    const ok = s==='success'||s==='done';
    let oh = '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">'+(ok?'✅ ':'❌ ')+'<span style="font-size:14px;font-weight:600;">'+s.toUpperCase()+'</span>';
    if (o.attempts>0) oh+='<span style="font-size:12px;color:var(--text-muted);">'+o.attempts+' attempts</span>';
    if (o.failure_category) oh+='<span class="ga-tc-failure-tag" style="background:var(--danger-light);color:var(--danger);">'+_escHtml(o.failure_category)+'</span>';
    oh += '</div>'; if (o.failure_detail) oh+='<div style="margin-top:8px;font-size:13px;padding:10px;background:#FEF2F2;border-radius:6px;">'+_escHtml(o.failure_detail)+'</div>';
    if (trace.run_id) oh+='<div style="margin-top:8px;font-size:11px;color:var(--text-muted);font-family:var(--font-mono);">Run ID: '+_escHtml(trace.run_id)+'</div>';
    h += _tcCard(ok?'🏁':'💥','Outcome',ok?'pass':'fail',true,oh);
    return h;
  }

  function _tcCard(icon, label, badge, open, body) {
    return '<div class="ga-tc-card'+(open?' open':'')+'"><div class="ga-tc-card-header" onclick="this.parentElement.classList.toggle(\'open\')">'+
      '<span class="ga-tc-icon">'+icon+'</span><span class="ga-tc-label">'+_escHtml(label)+'</span>'+
      '<span class="ga-tc-badge '+badge+'">'+badge.toUpperCase()+'</span><span class="ga-tc-chevron">▶</span></div>'+
      '<div class="ga-tc-card-body">'+body+'</div></div>';
  }

  function _escHtml(s) { const d = document.createElement('div'); d.appendChild(document.createTextNode(String(s||''))); return d.innerHTML; }
  function _escAttr(s) { return String(s||'').replace(/&/g,'&').replace(/"/g,'"').replace(/</g,'<').replace(/>/g,'>'); }

  /* ─── WebSocket ────────────────────────────────────────────────────────── */
  function connectWs(payload) {
    S.ws = new WebSocket(BACKEND.replace(/^http/,'ws') + '/designs/' + S.designId + '/chat');
    S.ws.onopen = () => S.ws.send(JSON.stringify(typeof payload==='string'?{type:'message',text:payload}:payload));
    S.ws.onmessage = e => { try { handleEvent(JSON.parse(e.data)); } catch (_) {} };
    S.ws.onerror = () => { traceLog('WebSocket lost.','error'); unlockSend(); };
    S.ws.onclose = () => { if (S.sending) unlockSend(); };
  }

  function handleEvent(evt) {
    switch (evt.type) {
      case 'thinking': setStatus('thinking'); traceLog('Agent is planning...','thinking'); break;
      case 'plan': setStatus('plan-ready'); traceLog('Plan generated:\n'+JSON.stringify(evt.plan,null,2),'plan'); break;
      case 'ask_user': case 'needs_user': setStatus('awaiting-input'); hideAssistant(); traceLog('Agent needs clarification: '+evt.question,'meta'); if (evt.question) showAssistant('<p>'+evt.question+'</p>',true); unlockSend(); break;
      case 'generating': setStatus('generating'); traceLog('Starting geometry pipeline...','stage'); break;
      case 'stage': setStatus('stage-'+evt.stage); traceLog(evt.stage.includes('replan')?'⚠ Replanning: '+evt.stage:'→ Stage: '+evt.stage, evt.stage.includes('replan')?'replan':'stage'); break;
      case 'success':
        setStatus('success'); S.runId = evt.run_id; traceLog('✅ SUCCESS! Run ID: '+(evt.run_id||''),'success');
        if (evt.run_id) {
          const dl = el('ga-btn-dl-stl'), ds = el('ga-btn-dl-step'), vt = el('ga-btn-view-trace'), lb = el('ga-studio-run-label');
          if (dl) dl.onclick = () => window.open(BACKEND+'/runs/'+evt.run_id+'/stl');
          if (ds) ds.onclick = () => window.open(BACKEND+'/runs/'+evt.run_id+'/step');
          if (vt) vt.onclick = () => viewTrace(evt.run_id);
          if (lb) lb.textContent = 'Run: '+(evt.run_id||'').substring(0,14)+'…';
        }
        if (S.useForgeCAD && S.forgecadOnline) { const ifr = el('ga-studio-iframe'); if (ifr) ifr.src = FORGECAD_URL; showView('studio'); }
        unlockSend(); break;
      case 'failed': setStatus('failed'); traceLog('❌ Failed ['+(evt.category||'unknown')+']: '+(evt.message||''),'failed'); unlockSend(); break;
      case 'error': setStatus('error'); traceLog('⚠ Error: '+(evt.message||'unknown'),'error'); unlockSend(); break;
    }
  }

  function unlockSend() { S.sending = false; const b = el('ga-send'); if (b) b.disabled = false; const i = el('ga-input'); if (i) i.disabled = false; }

  /* ─── Send ─────────────────────────────────────────────────────────────── */
  function sendMsg(text) {
    if (!text || S.sending) return; S.sending = true;
    const sb = el('ga-send'); if (sb) sb.disabled = true;
    const inp = el('ga-input'); if (inp) inp.disabled = true;
    const fi = el('ga-file'); const files = fi?.files ? Array.from(fi.files) : [];
    if (!S.designId) {
      hideAssistant(); clearTrace(); traceLog('Creating session...','meta');
      fetch(BACKEND+'/designs',{method:'POST'}).then(r=>r.json()).then(async data=>{
        S.designId = data.design_id; traceLog('Session: '+S.designId.substring(0,12)+'…','meta');
        await _syncConfig();
        const p = {type:'message',text}; if (files.length) { try { p.attachments = await encodeAttachments(files); } catch(e) { traceLog('Attachment error: '+e.message,'error'); } }
        traceLog('Connecting to WebSocket...','meta'); connectWs(p);
        if (fi) fi.value = ''; const fn = el('ga-file-name'); if (fn) fn.textContent = 'No file chosen';
      }).catch(e=>{ traceLog('Connection failed: '+e.message,'error'); unlockSend(); });
    } else {
      if (S.ws && S.ws.readyState === WebSocket.OPEN) { traceLog('Sending: '+text,'meta'); S.ws.send(JSON.stringify({type:'message',text})); }
      else { traceLog('WebSocket disconnected.','error'); unlockSend(); }
    }
  }

  function readFileAsDataUrl(f) { return new Promise((rs,rj)=>{ const r=new FileReader(); r.onload=()=>rs(String(r.result||'')); r.onerror=()=>rj(new Error('Could not read '+f.name)); r.readAsDataURL(f); }); }
  function encodeAttachments(files) { return Promise.all(files.map(f=>readFileAsDataUrl(f).then(u=>{ let b=u; if (b.includes(',')) b=b.split(',')[1]; return {filename:f.name,mime_type:f.type||'image/png',data:b}; }))); }

  /* ─── Boot ─────────────────────────────────────────────────────────────── */
  function boot() { healthCheck(); setInterval(healthCheck, 20000); showView('new-run'); }

  window.__gah = {
    send: () => { const i = el('ga-input'); sendMsg(i ? i.value.trim() : ''); },
    showView, reset: resetUI, toggleTemporal, toggleForgeCAD,
    openTemporal, openForgeCAD, viewTrace, closeTrace,
  };
  document.addEventListener('DOMContentLoaded', boot);
})();