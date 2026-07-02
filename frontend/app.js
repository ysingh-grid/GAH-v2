/**
 * GAH frontend — Form-based UI + APIs.
 *
 * Every button in the nav bar is functional:
 *   - New run:      resets the form and clears the chat
 *   - Runs:         fetches /api/runs, renders a table
 *   - Analytics:    fetches /api/analytics, renders metric cards
 *   - Temporal:     opens the Temporal Web UI (if running)
 *   - ForgeCAD:     opens ForgeCAD Studio (if running)
 *   - Send:         creates a design session + opens a WebSocket
 */

(function () {
  'use strict';

  /* ─── Constants ────────────────────────────────────────────────────────── */
  var BACKEND = window.BACKEND_URL || 'http://localhost:8001';
  var TEMPORAL_URL = 'http://localhost:8088';
  var FORGECAD_URL = 'http://localhost:4000';

  /* Service availability flags (set by healthCheck) */
  var temporalAvailable = false;
  var forgecadAvailable = false;

  /* ─── State ────────────────────────────────────────────────────────────── */
  var S = {
    designId: null,
    ws: null,
    sending: false,
    currentStage: null,
  };

  function el(id) { return document.getElementById(id); }

  /* ─── Boot ─────────────────────────────────────────────────────────────── */

  function boot() {
    // 1. Fetch runtime config from backend (sets ForgeCAD URL if configured)
    fetch(BACKEND + '/config')
      .then(function (r) { return r.ok ? r.json() : {}; })
      .catch(function () { return {}; })
      .then(function (cfg) {
        if (cfg && cfg.forgecad_studio_url) {
          FORGECAD_URL = cfg.forgecad_studio_url;
        }
        // After config is loaded, probe external services
        probeService(FORGECAD_URL, 'forgecad');
        probeService(TEMPORAL_URL, 'temporal');
      });
  }

  /**
   * Probe whether an external service is reachable.
   * Updates the status-dot indicator in the nav bar.
   */
  function probeService(url, serviceId) {
    if (!url) {
      setDot(serviceId, false);
      return;
    }
    fetch(url, { mode: 'no-cors', cache: 'no-store' })
      .then(function () {
        // mode: no-cors → opaque response. If we get here, the server answered.
        setDot(serviceId, true);
        if (serviceId === 'forgecad') forgecadAvailable = true;
        if (serviceId === 'temporal') temporalAvailable = true;
      })
      .catch(function () {
        setDot(serviceId, false);
      });
  }

  function setDot(serviceId, isUp) {
    var dotId = serviceId === 'forgecad' ? 'ga-forgecad-dot' : 'ga-temporal-dot';
    var dot = el(dotId);
    if (!dot) return;
    dot.classList.remove('ga-dot-unknown', 'ga-dot-up', 'ga-dot-down');
    dot.classList.add(isUp ? 'ga-dot-up' : 'ga-dot-down');
  }

  /* ─── Navigation ───────────────────────────────────────────────────────── */

  function showView(viewId) {
    document.querySelectorAll('.ga-view').forEach(function (v) {
      v.style.display = 'none';
    });
    var v = el('ga-' + viewId + '-view');
    if (v) v.style.display = viewId === 'studio' ? 'block' : 'flex';

    if (viewId === 'runs') fetchRuns();
    if (viewId === 'analytics') fetchAnalytics();
  }

  function openTemporal() {
    if (temporalAvailable) {
      window.open(TEMPORAL_URL, '_blank', 'noopener');
    } else {
      showUnavailable(
        'Temporal UI',
        'The Temporal Web UI is not running at <code>' + TEMPORAL_URL + '</code>.<br><br>' +
        'To start it, run:<br><code>docker compose --profile temporal up</code>'
      );
    }
  }

  function openForgeCAD() {
    if (forgecadAvailable) {
      window.open(FORGECAD_URL, '_blank', 'noopener');
    } else {
      showUnavailable(
        'ForgeCAD Studio',
        'ForgeCAD Studio is not running at <code>' + FORGECAD_URL + '</code>.<br><br>' +
        'To start it, run:<br><code>FORGECAD_STUDIO_URL=' + FORGECAD_URL + ' docker compose --profile studio up</code>'
      );
    }
  }

  function showUnavailable(title, msg) {
    showView('unavailable');
    var t = el('ga-unavail-title');
    var m = el('ga-unavail-msg');
    if (t) t.textContent = title + ' — Not Running';
    if (m) m.innerHTML = msg;
  }

  /* ─── Reset UI (New Run) ───────────────────────────────────────────────── */

  function resetUI() {
    var inp = el('ga-input');
    if (inp) { inp.value = ''; inp.disabled = false; }
    var fileName = el('ga-file-name');
    if (fileName) fileName.textContent = 'No file chosen';
    var area = el('ga-assistant-area');
    if (area) area.innerHTML = '';

    S.designId = null;
    if (S.ws) {
      try { S.ws.close(); } catch (_) { /* ignore */ }
      S.ws = null;
    }
    S.sending = false;

    var sendBtn = el('ga-send');
    if (sendBtn) sendBtn.disabled = false;
    showView('form');
  }

  /* ─── WebSocket chat ───────────────────────────────────────────────────── */

  function connectWs(textToSend, callback) {
    var wsBase = BACKEND.replace(/^http/, 'ws');
    S.ws = new WebSocket(wsBase + '/designs/' + S.designId + '/chat');

    S.ws.onopen = function () {
      S.ws.send(JSON.stringify({ type: 'message', text: textToSend }));
      if (callback) callback();
    };

    S.ws.onmessage = function (e) {
      try { handleEvent(JSON.parse(e.data)); } catch (_) { /* ignore parse errors */ }
    };

    S.ws.onerror = function () {
      appendAssistantMessage('⚠️ WebSocket error — check backend logs.');
      unlockSend();
    };

    S.ws.onclose = function () {
      // Allow new submissions after WS closes
      if (S.sending) unlockSend();
    };
  }

  function handleEvent(evt) {
    switch (evt.type) {
      case 'thinking':
        appendAssistantMessage('🧠 Thinking…');
        break;
      case 'ask_user':
        appendAssistantMessage(evt.question || 'Please provide more details.', true);
        unlockSend();
        break;
      case 'generating':
        appendAssistantMessage('⚙️ Generating 3D Model… Please wait.');
        break;
      case 'stage':
        var m = el('ga-stage-msg');
        if (m) m.textContent = 'Stage: ' + evt.stage;
        break;
      case 'success':
        appendAssistantMessage('✅ Model generated successfully! Run: ' + (evt.run_id || ''));
        if (forgecadAvailable) {
          // Load the ForgeCAD studio in the iframe
          var iframe = el('ga-iframe');
          if (iframe) iframe.src = FORGECAD_URL;
          showView('studio');
        }
        unlockSend();
        break;
      case 'needs_user':
        appendAssistantMessage(evt.question || 'I need more information to continue.', true);
        unlockSend();
        break;
      case 'failed':
        appendAssistantMessage('❌ Generation failed [' + (evt.category || 'unknown') + ']: ' + (evt.message || ''));
        unlockSend();
        break;
      case 'error':
        appendAssistantMessage('⚠️ Server error: ' + (evt.message || 'unknown'));
        unlockSend();
        break;
    }
  }

  function unlockSend() {
    S.sending = false;
    var sendBtn = el('ga-send');
    if (sendBtn) sendBtn.disabled = false;
    var inp = el('ga-input');
    if (inp) inp.disabled = false;
  }

  function sendMsg(text) {
    if (!text) {
      appendAssistantMessage('⚠️ Please enter a design prompt first.');
      return;
    }
    if (S.sending) return;
    S.sending = true;

    var sendBtn = el('ga-send');
    if (sendBtn) sendBtn.disabled = true;
    var inp = el('ga-input');
    if (inp) inp.disabled = true;

    if (!S.designId) {
      // First message — create a design session, then connect WebSocket
      fetch(BACKEND + '/designs', { method: 'POST' })
        .then(function (r) {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.json();
        })
        .then(function (data) {
          S.designId = data.design_id;
          connectWs(text, function () {
            appendAssistantMessage('📤 Submitting prompt…');
          });
        })
        .catch(function (e) {
          appendAssistantMessage('❌ Error connecting to backend: ' + e.message);
          unlockSend();
        });
    } else {
      // Follow-up message on an open WebSocket
      if (S.ws && S.ws.readyState === WebSocket.OPEN) {
        S.ws.send(JSON.stringify({ type: 'message', text: text }));
      } else {
        appendAssistantMessage('⚠️ Connection lost. Click "New run" to start fresh.');
        unlockSend();
      }
    }
  }

  /* ─── Assistant message rendering ──────────────────────────────────────── */

  function appendAssistantMessage(text, requiresInput) {
    var area = el('ga-assistant-area');
    if (!area) return;

    var div = document.createElement('div');
    div.className = 'ga-assistant-msg';

    var msg = document.createElement('p');
    msg.style.marginBottom = requiresInput ? '12px' : '0';
    msg.innerHTML = text.replace(/\\n/g, '<br>');
    div.appendChild(msg);

    if (requiresInput) {
      var ta = document.createElement('textarea');
      ta.className = 'ga-reply-textarea';
      ta.placeholder = 'Your answer…';

      var btn = document.createElement('button');
      btn.textContent = 'Reply →';
      btn.className = 'ga-btn-primary';
      btn.onclick = function () {
        if (!ta.value.trim()) return;
        ta.disabled = true;
        btn.disabled = true;
        sendMsg(ta.value.trim());
      };

      div.appendChild(ta);
      div.appendChild(btn);
    } else {
      var stageMsg = document.createElement('div');
      stageMsg.id = 'ga-stage-msg';
      stageMsg.style.fontSize = '12px';
      stageMsg.style.marginTop = '8px';
      div.appendChild(stageMsg);
    }

    area.appendChild(div);
    // Auto-scroll to the latest message
    area.scrollTop = area.scrollHeight;
  }

  /* ─── Runs ─────────────────────────────────────────────────────────────── */

  function fetchRuns() {
    var tb = document.querySelector('#ga-runs-table tbody');
    if (!tb) return;
    tb.innerHTML = '<tr><td colspan="3" class="ga-loading">Loading runs…</td></tr>';

    fetch(BACKEND + '/api/runs')
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (data) {
        if (!data.runs || data.runs.length === 0) {
          tb.innerHTML = '<tr><td colspan="3" class="ga-empty">No runs found. Submit a design prompt to get started!</td></tr>';
          return;
        }
        tb.innerHTML = data.runs.map(function (run) {
          var date = new Date(run.created_at * 1000).toLocaleString();
          var sClass = run.status === 'success' ? 'status-success' : 'status-failed';
          var icon = run.status === 'success' ? '✅' : '❌';
          return '<tr><td>' + run.run_id + '</td><td>' + date + '</td><td class="' + sClass + '">' + icon + ' ' + run.status + '</td></tr>';
        }).join('');
      })
      .catch(function (e) {
        tb.innerHTML = '<tr><td colspan="3" class="ga-error">Failed to load runs: ' + e.message + '</td></tr>';
      });
  }

  /* ─── Analytics ────────────────────────────────────────────────────────── */

  function fetchAnalytics() {
    var container = el('ga-analytics-cards');
    if (!container) return;
    container.innerHTML = '<p class="ga-loading">Loading analytics…</p>';

    fetch(BACKEND + '/api/analytics')
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (data) {
        container.innerHTML =
          '<div class="ga-metric-card">' +
            '<h3>Total Runs</h3>' +
            '<div class="value">' + data.total_runs + '</div>' +
          '</div>' +
          '<div class="ga-metric-card">' +
            '<h3>Success Rate</h3>' +
            '<div class="value">' + data.success_rate + '</div>' +
          '</div>' +
          '<div class="ga-metric-card ga-card-success">' +
            '<h3>Successful Runs</h3>' +
            '<div class="value">' + data.successful_runs + '</div>' +
          '</div>' +
          '<div class="ga-metric-card ga-card-fail">' +
            '<h3>Failed Runs</h3>' +
            '<div class="value">' + data.failed_runs + '</div>' +
          '</div>';
      })
      .catch(function (e) {
        container.innerHTML = '<p class="ga-error">Failed to load analytics: ' + e.message + '</p>';
      });
  }

  /* ─── Public API ───────────────────────────────────────────────────────── */

  window.__gah = {
    send: function () {
      var inp = el('ga-input');
      sendMsg(inp ? inp.value.trim() : '');
    },
    showView: showView,
    reset: resetUI,
    openTemporal: openTemporal,
    openForgeCAD: openForgeCAD,
  };

  document.addEventListener('DOMContentLoaded', boot);

})();
