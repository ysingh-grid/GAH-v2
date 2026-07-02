/**
 * GAH frontend — forge-assistant.js visual design + M8 WebSocket API.
 *
 * WS protocol (server → client):
 *   thinking   — planner running; show typing dots
 *   ask_user   — question + options; assistant bubble
 *   generating — geometry loop started; show progress panel
 *   stage      — {stage}; live coarse-stage progress from the Temporal workflow
 *                (DesignStage.*: planning|generating|inspecting|repairing|verifying|done)
 *   success    — {forge_js, plan, run_id}; done banner + main view
 *   needs_user — mid-generation question; assistant bubble
 *   failed     — {category, message}; error stage chip
 *   error      — unexpected server exception
 */

(function () {
  'use strict';

  var BACKEND = window.BACKEND_URL || 'http://localhost:8001';

  // Pipeline stage labels (matches Capstone visual design)
  var STAGES = ['PLANNING', 'GENERATING', 'VERIFYING', 'DONE'];
  var STAGE_ICONS = { PLANNING: '🧠', GENERATING: '⌨️', VERIFYING: '🔍', DONE: '✅', FAILED: '❌' };

  // Backend DesignStage (Temporal workflow) → the 4 UI chips above.
  // The fine geometry sub-stages (inspecting/repairing) live inside the GENERATING
  // coarse activity, so they collapse onto the GENERATING chip.
  var STAGE_MAP = {
    planning:   'PLANNING',
    generating: 'GENERATING',
    inspecting: 'GENERATING',
    repairing:  'GENERATING',
    verifying:  'VERIFYING',
    replanning: 'PLANNING',   // loop-back: bar returns to PLANNING; labeled below
    done:       'DONE',
  };

  // ── State ─────────────────────────────────────────────────────────────────
  var S = {
    designId:    null,
    ws:          null,
    panelOpen:   false,
    booted:      false,    // first open triggered boot
    sending:     false,
    params:      {},       // accumulated params from plan steps
    pendingFiles: [],
    currentStage: null,
  };

  // ── Helpers ───────────────────────────────────────────────────────────────

  function now() {
    return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  function fmt(t) {
    return String(t || '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\n/g, '<br>');
  }

  function el(id) { return document.getElementById(id); }

  function setConn(state) {
    var dot = el('ga-conn-dot');
    if (!dot) return;
    dot.className = 'ga-conn-dot ' + state;
    dot.title = state.charAt(0).toUpperCase() + state.slice(1);
  }

  function setInput(enabled) {
    var inp = el('ga-input');
    var btn = el('ga-send');
    var att = el('ga-attach');
    if (inp) inp.disabled = !enabled;
    if (btn) btn.disabled = !enabled;
    if (att) att.disabled = !enabled;
  }

  function setAttachments(files) {
    S.pendingFiles = files || [];
    var input = el('ga-file');
    if (input && !S.pendingFiles.length) {
      input.value = '';
    }
    renderAttachmentBar();
  }

  function renderAttachmentBar() {
    var bar = el('ga-attachment-bar');
    if (!bar) return;
    if (!S.pendingFiles.length) {
      bar.style.display = 'none';
      bar.textContent = '';
      return;
    }
    bar.style.display = 'block';
    bar.textContent = S.pendingFiles.map(function (file) {
      return file.name;
    }).join(', ');
  }

  function pickAttachments() {
    var file = el('ga-file');
    if (file) file.click();
  }

  function handleAttachmentPick(input) {
    var files = Array.from((input && input.files) || []).filter(function (file) {
      return /^image\//.test(file.type || '');
    });
    setAttachments(files);
  }

  function readFileAsDataUrl(file) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () { resolve(String(reader.result || '')); };
      reader.onerror = function () { reject(new Error('Could not read ' + file.name)); };
      reader.readAsDataURL(file);
    });
  }

  async function encodeAttachments(files) {
    return Promise.all(files.map(function (file) {
      return readFileAsDataUrl(file).then(function (dataUrl) {
        var payload = {
          filename: file.name,
          mime_type: file.type || 'image/png',
          data: dataUrl,
        };
        return payload;
      });
    }));
  }

  renderAttachmentBar();

  // ── Boot: POST /designs + WS connect ─────────────────────────────────────

  function boot() {
    setConn('connecting');
    setInput(false);

    // Fetch runtime config first (sets window.FORGECAD_STUDIO_URL from docker-compose env).
    // Failure is non-fatal — continue to session creation regardless.
    fetch(BACKEND + '/config')
      .then(function (r) { return r.ok ? r.json() : {}; })
      .catch(function () { return {}; })
      .then(function (cfg) {
        if (cfg && cfg.forgecad_studio_url) {
          window.FORGECAD_STUDIO_URL = cfg.forgecad_studio_url;
          // Show studio as background immediately — don't wait for a design
          el('ga-hero').style.display = 'none';
          el('ga-studio').style.display = 'block';
          el('ga-iframe').src = cfg.forgecad_studio_url;
        }
        return fetch(BACKEND + '/designs', { method: 'POST' });
      })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (data) {
        S.designId = data.design_id;
        connectWs();
      })
      .catch(function (e) {
        setConn('error');
        appendMsg('system', '⚠️ Cannot reach backend at ' + BACKEND + ' — ' + e.message);
      });
  }

  function connectWs() {
    var wsBase = BACKEND.replace(/^http/, 'ws');
    S.ws = new WebSocket(wsBase + '/designs/' + S.designId + '/chat');

    S.ws.onopen = function () {
      setConn('connected');
      setInput(true);
    };

    S.ws.onmessage = function (e) {
      try { handleEvent(JSON.parse(e.data)); } catch (_) {}
    };

    S.ws.onerror = function () {
      setConn('error');
      appendMsg('system', '⚠️ WebSocket error — check backend logs.');
    };

    S.ws.onclose = function (ev) {
      if (ev.code !== 1000 && ev.code !== 1005 && S.currentStage !== 'DONE') {
        setConn('error');
        appendMsg('system', '⚠️ Connection closed. Refresh to reconnect.');
      }
    };
  }

  // ── Outgoing ──────────────────────────────────────────────────────────────

  async function sendMsg() {
    var inp = el('ga-input');
    var txt = inp ? inp.value.trim() : '';
    if (!txt && !S.pendingFiles.length) return;
    if (!S.ws || S.ws.readyState !== WebSocket.OPEN) return;
    if (S.sending) return;

    S.sending = true;
    var files = S.pendingFiles.slice();
    setAttachments([]);

    try {
      var payload = { type: 'message', text: txt };
      if (files.length) {
        payload.attachments = await encodeAttachments(files);
      }
      S.ws.send(JSON.stringify(payload));
      appendMsg('user', txt || ('[image attached: ' + files.map(function (file) {
        return file.name;
      }).join(', ') + ']'));
      if (inp) {
        inp.value = '';
        inp.style.height = 'auto';
      }
      setInput(false);
      hideSuggestions();
      showTyping();
    } catch (e) {
      appendMsg('system', '⚠️ Could not send attachment: ' + (e && e.message ? e.message : e));
      setAttachments(files);
      setInput(true);
    } finally {
      S.sending = false;
    }
  }

  // ── Incoming events ───────────────────────────────────────────────────────

  function handleEvent(evt) {
    switch (evt.type) {

      case 'thinking':
        showTyping();
        break;

      case 'ask_user':
        hideTyping();
        appendMsg('assistant', evt.question || '');
        if (evt.options && evt.options.length) appendOptions(evt.options);
        setInput(true);
        break;

      case 'generating':
        hideTyping();
        showProgress('PLANNING');
        // don't re-enable input — auto-generating
        break;

      case 'stage': {
        // Live coarse-stage progress from the Temporal workflow.
        var chip = STAGE_MAP[evt.stage];
        if (chip) {
          if (el('ga-progress').classList.contains('visible')) {
            advanceProgress(chip);
          } else {
            showProgress(chip);
          }
          // Replan maps onto the PLANNING chip (loop-back). Label it so the user
          // sees a distinct "fixing geometry" step instead of an unexplained reset.
          if (evt.stage === 'replanning') {
            var pmsg = el('ga-prog-msg');
            if (pmsg) pmsg.textContent = '↻ Replanning — fixing the geometry…';
          }
        }
        break;
      }

      case 'success':
        hideTyping();
        advanceProgress('DONE');
        showOutput(evt);
        el('ga-fab').classList.add('has-notif');
        break;

      case 'needs_user':
        hideTyping();
        hideProgress();
        appendMsg('assistant', evt.question || 'I need more information to continue.');
        if (evt.options && evt.options.length) appendOptions(evt.options);
        setInput(true);
        break;

      case 'failed':
        hideTyping();
        failProgress(evt.category || 'unknown');
        appendMsg('system', 'Generation failed [' + (evt.category || 'unknown') + ']: ' + (evt.message || ''));
        setInput(true);
        break;

      case 'error':
        hideTyping();
        hideProgress();
        appendMsg('system', '⚠️ Server error: ' + (evt.message || 'unknown'));
        setInput(true);
        break;
    }
  }

  // ── DOM: messages ─────────────────────────────────────────────────────────

  function appendMsg(role, text) {
    var body = el('ga-body');
    if (!body) return;
    var row = document.createElement('div');
    row.className = 'ga-msg ' + role;
    row.innerHTML = '<div class="ga-bubble">' + fmt(text) + '</div>'
      + '<div class="ga-time">' + now() + '</div>';
    body.appendChild(row);
    body.scrollTop = body.scrollHeight;
  }

  function appendOptions(options) {
    var body = el('ga-body');
    if (!body) return;
    var wrap = document.createElement('div');
    wrap.className = 'ga-options';
    options.forEach(function (opt) {
      var btn = document.createElement('button');
      btn.className = 'ga-opt';
      btn.textContent = opt;
      btn.addEventListener('click', function () {
        var inp = el('ga-input');
        if (inp) inp.value = opt;
        sendMsg();
      });
      wrap.appendChild(btn);
    });
    body.appendChild(wrap);
    body.scrollTop = body.scrollHeight;
  }

  function showTyping() {
    if (el('ga-typing')) return;
    var body = el('ga-body');
    if (!body) return;
    var d = document.createElement('div');
    d.id = 'ga-typing';
    d.className = 'ga-msg assistant';
    d.innerHTML = '<div class="ga-typing-bubble"><div class="ga-dots"><span></span><span></span><span></span></div></div>';
    body.appendChild(d);
    body.scrollTop = body.scrollHeight;
  }

  function hideTyping() {
    var t = el('ga-typing');
    if (t) t.remove();
  }

  // ── DOM: suggestions ──────────────────────────────────────────────────────

  function hideSuggestions() {
    var s = el('ga-suggestions');
    if (s) s.style.display = 'none';
  }

  // ── DOM: params strip ─────────────────────────────────────────────────────

  function updateParams(params) {
    if (!params || !Object.keys(params).length) return;
    Object.assign(S.params, params);
    var strip = el('ga-params');
    var chips = el('ga-chips');
    if (!strip || !chips) return;
    strip.classList.add('visible');
    chips.innerHTML = Object.entries(S.params).map(function (kv) {
      return '<span class="ga-chip">' + kv[0].replace(/_/g, ' ') + ': <strong>' + kv[1] + '</strong></span>';
    }).join('');
  }

  // ── DOM: progress panel ───────────────────────────────────────────────────

  function renderStages(currentStage) {
    var row = el('ga-stage-row');
    if (!row) return;
    var curIdx = STAGES.indexOf(currentStage);
    row.innerHTML = STAGES.map(function (s, i) {
      var cls = 'ga-stage-chip';
      if (currentStage === 'FAILED' && s === 'DONE') {
        cls += ' error';
      } else if (i < curIdx) {
        cls += ' done';
      } else if (s === currentStage) {
        cls += ' active';
      }
      return '<span class="' + cls + '">' + (STAGE_ICONS[s] || '') + ' ' + s + '</span>';
    }).join('');
    var stageEl = el('ga-prog-stage');
    if (stageEl) stageEl.textContent = currentStage;
  }

  function showProgress(stage) {
    S.currentStage = stage;
    el('ga-progress').classList.add('visible');
    el('ga-done').classList.remove('visible');
    renderStages(stage);
    var msg = el('ga-prog-msg');
    if (msg) msg.textContent = '';
  }

  function advanceProgress(stage) {
    S.currentStage = stage;
    renderStages(stage);
    var msg = el('ga-prog-msg');
    if (msg) msg.textContent = stage === 'DONE' ? 'Design ready.' : '';
  }

  function failProgress(category) {
    S.currentStage = 'FAILED';
    var row = el('ga-stage-row');
    if (row) {
      // mark all chips as muted except last as error
      Array.from(row.querySelectorAll('.ga-stage-chip')).forEach(function (c) {
        c.className = 'ga-stage-chip';
      });
      var last = row.querySelector('.ga-stage-chip:last-child');
      if (last) last.className = 'ga-stage-chip error';
    }
    var msg = el('ga-prog-msg');
    if (msg) msg.textContent = '✗ ' + category;
  }

  function hideProgress() {
    el('ga-progress').classList.remove('visible');
  }

  // ── DOM: output in main area ──────────────────────────────────────────────

  function showOutput(evt) {
    var studioUrl = window.FORGECAD_STUDIO_URL;

    if (studioUrl) {
      el('ga-hero').style.display = 'none';
      el('ga-studio').style.display = 'block';
      // ForgeCAD Studio runs its own internal file-watcher (chokidar) on the
      // /workspace directory. Once the backend writes main.forge.js to disk,
      // the Studio live-reloads the 3D viewport automatically — no iframe
      // navigation needed. Just make sure the iframe is pointed at the Studio.
      var iframe = el('ga-iframe');
      if (!iframe.src || iframe.src === 'about:blank') {
        iframe.src = studioUrl;
      }
    } else {
      el('ga-hero').style.display = 'none';
      el('ga-code').style.display = 'flex';
      el('ga-code-pre').textContent = evt.forge_js || '// (no forge script returned)';
    }

    // Extract params from plan steps
    var plan = evt.plan;
    if (plan && plan.steps && plan.steps.length) {
      var extracted = {};
      plan.steps.forEach(function (step) {
        Object.assign(extracted, step.parameters || {});
      });
      updateParams(extracted);
    }

    // Done banner
    var done = el('ga-done');
    done.classList.add('visible');
    var doneFile = el('ga-done-file');
    if (doneFile) doneFile.textContent = 'run_id: ' + (evt.run_id || '—');

    // Hide progress, show done
    el('ga-progress').classList.remove('visible');

    // Assistant message
    appendMsg('assistant', '✅ Design ready! Check the viewport — or copy the .forge.js code.');
  }

  // ── Toggle panel ──────────────────────────────────────────────────────────

  function toggle() {
    S.panelOpen = !S.panelOpen;
    el('ga-panel').classList.toggle('open', S.panelOpen);
    el('ga-fab').classList.toggle('open', S.panelOpen);

    if (S.panelOpen) {
      if (!S.booted) {
        S.booted = true;
        boot();
      }
      // Check if suggestions should be hidden (messages exist beyond greeting)
      var body = el('ga-body');
      if (body && body.childElementCount > 1) hideSuggestions();

      setTimeout(function () {
        var inp = el('ga-input');
        if (inp && !inp.disabled) inp.focus();
      }, 370);
    }
  }

  // ── Public API (window.__gah) ─────────────────────────────────────────────

  window.__gah = {
    toggle: toggle,

    send: sendMsg,

    pick: pickAttachments,

    files: handleAttachmentPick,

    suggest: function (btn) {
      var inp = el('ga-input');
      if (!inp) return;
      inp.value = btn.textContent.trim();
      hideSuggestions();

      if (!S.panelOpen) {
        toggle();
        // Wait for boot + WS connect then send
        var tries = 0;
        var check = setInterval(function () {
          tries++;
          if (S.ws && S.ws.readyState === WebSocket.OPEN) {
            clearInterval(check);
            sendMsg();
          } else if (tries > 50) {
            clearInterval(check);
          }
        }, 100);
      } else {
        sendMsg();
      }
    },

    resize: function (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = Math.min(textarea.scrollHeight, 96) + 'px';
    },

    key: function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMsg();
      }
    },

    copyCode: function () {
      var pre = el('ga-code-pre');
      if (!pre || !pre.textContent) return;
      navigator.clipboard.writeText(pre.textContent).then(function () {
        var btn = el('ga-copy-btn');
        if (!btn) return;
        var orig = btn.textContent;
        btn.textContent = 'Copied!';
        setTimeout(function () { btn.textContent = orig; }, 1500);
      });
    },
  };

})();
