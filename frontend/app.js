/**
 * GAH frontend — chat WebSocket client + preview panel.
 *
 * Protocol (server → client events):
 *   thinking   — planner is computing, show dots
 *   ask_user   — planner question + options, re-enable input
 *   generating — geometry loop running, show spinner
 *   success    — {forge_js, plan, run_id}, show output
 *   needs_user — loop escalated, show question, re-enable input
 *   failed     — {category, message}, show error
 *   error      — unexpected exception from server
 *
 * All state lives in DesignChat; DOM manipulation is isolated to the render*()
 * helpers so the logic is easy to read top-to-bottom.
 */

const BACKEND_URL = window.BACKEND_URL || 'http://localhost:8001';

class DesignChat {
  constructor() {
    this._designId   = null;
    this._ws         = null;
    this._state      = 'idle';  // idle | chatting | thinking | generating | done | failed
    this._lastPlan   = null;
    this._lastForgeJs = null;
    this._activeTab  = 'forge';  // which preview tab is shown

    // DOM refs (assigned in init())
    this._messages        = null;
    this._userInput       = null;
    this._sendBtn         = null;
    this._statusBadge     = null;
    this._thinkingEl      = null;
    this._genOverlay      = null;
    this._genStage        = null;
    this._previewEmpty    = null;
    this._forgeIframeWrap = null;
    this._forgeCodeWrap   = null;
    this._planWrap        = null;
    this._connBanner      = null;
  }

  // ── Boot ────────────────────────────────────────────────────────────────────

  async init() {
    this._bindDom();
    this._bindUiEvents();
    await this._createSession();
    this._connectWs();
  }

  _bindDom() {
    this._messages        = document.getElementById('messages');
    this._userInput       = document.getElementById('user-input');
    this._sendBtn         = document.getElementById('send-btn');
    this._statusBadge     = document.getElementById('status-badge');
    this._thinkingEl      = document.getElementById('thinking-indicator');
    this._genOverlay      = document.getElementById('generating-overlay');
    this._genStage        = document.getElementById('gen-stage');
    this._previewEmpty    = document.getElementById('preview-empty');
    this._forgeIframeWrap = document.getElementById('forge-iframe-wrap');
    this._forgeCodeWrap   = document.getElementById('forge-code-wrap');
    this._planWrap        = document.getElementById('plan-wrap');
    this._connBanner      = document.getElementById('conn-banner');
  }

  _bindUiEvents() {
    this._sendBtn.addEventListener('click', () => this._handleSend());
    this._userInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this._handleSend();
      }
    });
    // Tab switching
    document.querySelectorAll('.tab').forEach((tab) => {
      tab.addEventListener('click', () => this._switchTab(tab.dataset.tab));
    });
  }

  // ── Session + WebSocket setup ────────────────────────────────────────────────

  async _createSession() {
    try {
      const resp = await fetch(`${BACKEND_URL}/designs`, { method: 'POST' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const { design_id } = await resp.json();
      this._designId = design_id;
    } catch (err) {
      this._showBanner(`Cannot reach backend at ${BACKEND_URL}: ${err.message}`);
      throw err;
    }
  }

  _connectWs() {
    const wsUrl = BACKEND_URL.replace(/^http/, 'ws');
    this._ws = new WebSocket(`${wsUrl}/designs/${this._designId}/chat`);

    this._ws.onopen    = ()  => { this._hideBanner(); this._setState('chatting'); };
    this._ws.onmessage = (e) => this._handleEvent(JSON.parse(e.data));
    this._ws.onerror   = ()  => this._showBanner('WebSocket error — is the backend running?');
    this._ws.onclose   = (e) => {
      if (e.code !== 1000 && e.code !== 1005 && this._state !== 'done') {
        this._showBanner('WebSocket closed unexpectedly. Refresh to reconnect.');
      }
    };
  }

  // ── Outgoing messages ─────────────────────────────────────────────────────────

  _handleSend() {
    const text = this._userInput.value.trim();
    if (!text || !this._ws || this._ws.readyState !== WebSocket.OPEN) return;
    if (['thinking', 'generating'].includes(this._state)) return;

    this._ws.send(JSON.stringify({ type: 'message', text }));
    this._addMessage('user', text);
    this._userInput.value = '';
    this._setInputEnabled(false);
    this._hideThinking();
  }

  // ── Incoming event handling ──────────────────────────────────────────────────

  _handleEvent(event) {
    switch (event.type) {

      case 'thinking':
        this._setState('thinking');
        this._showThinking();
        break;

      case 'ask_user':
        this._hideThinking();
        this._setState('chatting');
        this._addMessage('planner', event.question, event.options || []);
        this._setInputEnabled(true);
        break;

      case 'generating':
        this._hideThinking();
        this._setState('generating');
        this._showGenerating(event.stage || 'working…');
        break;

      case 'success':
        this._hideGenerating();
        this._setState('done');
        this._lastForgeJs = event.forge_js || '';
        this._lastPlan    = event.plan || null;
        this._renderSuccess(event);
        // Input stays disabled — part is done; refresh for new session
        this._addMessage('system', `✓ Part generated! (run: ${event.run_id})`);
        break;

      case 'needs_user':
        this._hideGenerating();
        this._setState('needs_user');
        this._addMessage('planner', event.question, event.options || []);
        this._setInputEnabled(true);
        break;

      case 'failed':
        this._hideGenerating();
        this._setState('failed');
        this._addMessage('planner', `Generation failed [${event.category}]: ${event.message}`);
        this._setInputEnabled(true);  // allow the user to rephrase
        break;

      case 'error':
        this._hideGenerating();
        this._setState('error');
        this._addMessage('system', `Server error: ${event.message}`);
        this._setInputEnabled(true);
        break;
    }
  }

  // ── Render helpers ───────────────────────────────────────────────────────────

  _addMessage(role, text, options = []) {
    this._hideThinking();

    const wrap = document.createElement('div');
    const label = document.createElement('div');
    const msg   = document.createElement('div');

    label.className = 'message-label';
    label.textContent = role === 'user' ? 'You' : role === 'planner' ? 'Planner' : 'System';
    msg.className = `message ${role}`;
    msg.textContent = text;

    wrap.appendChild(label);
    wrap.appendChild(msg);

    if (options.length) {
      const optWrap = document.createElement('div');
      optWrap.className = 'options';
      options.forEach((opt) => {
        const btn = document.createElement('button');
        btn.className = 'option-btn';
        btn.textContent = opt;
        btn.addEventListener('click', () => {
          this._userInput.value = opt;
          this._handleSend();
        });
        optWrap.appendChild(btn);
      });
      wrap.appendChild(optWrap);
    }

    this._messages.appendChild(wrap);
    this._messages.scrollTop = this._messages.scrollHeight;
  }

  _showThinking() {
    if (this._thinkingEl.style.display !== 'none') return;
    this._thinkingEl.style.display = 'flex';
    this._messages.scrollTop = this._messages.scrollHeight;
  }

  _hideThinking() {
    this._thinkingEl.style.display = 'none';
  }

  _showGenerating(stage) {
    this._genStage.textContent = stage.replace(/_/g, ' ');
    this._genOverlay.style.display = 'flex';
  }

  _hideGenerating() {
    this._genOverlay.style.display = 'none';
  }

  _renderSuccess(event) {
    // Populate forge code tab
    const codeEl = document.getElementById('forge-code');
    codeEl.textContent = event.forge_js || '// (no forge script returned)';

    // Populate plan tab
    const planEl = document.getElementById('plan-json');
    planEl.textContent = JSON.stringify(event.plan, null, 2);

    // Try to load ForgeCAD studio iframe if the server URL is configured
    const studioUrl = window.FORGECAD_STUDIO_URL;
    if (studioUrl && event.run_id) {
      const iframe = document.getElementById('forge-iframe');
      iframe.src = `${studioUrl}?run_id=${event.run_id}`;
      this._switchTab('studio');
    } else {
      this._switchTab('forge');
    }

    this._showPreviewContent();
  }

  _showPreviewContent() {
    this._previewEmpty.style.display = 'none';
    this._switchTab(this._activeTab);
  }

  _switchTab(tabName) {
    this._activeTab = tabName;
    document.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
    const activeTab = document.querySelector(`.tab[data-tab="${tabName}"]`);
    if (activeTab) activeTab.classList.add('active');

    // All content hidden by default; show the selected one
    this._forgeIframeWrap.style.display = 'none';
    this._forgeCodeWrap.style.display   = 'none';
    this._planWrap.style.display        = 'none';

    if (!this._lastForgeJs && !this._lastPlan) return;  // nothing to show yet

    switch (tabName) {
      case 'studio': this._forgeIframeWrap.style.display = 'block'; break;
      case 'forge':  this._forgeCodeWrap.style.display   = 'block'; break;
      case 'plan':   this._planWrap.style.display        = 'block'; break;
    }
  }

  _setState(state) {
    this._state = state;
    const badge = this._statusBadge;
    badge.className = `${state}`;
    badge.id = 'status-badge';
    const labels = {
      idle: 'Idle', chatting: 'Chatting', thinking: 'Thinking…',
      generating: 'Generating', done: 'Done ✓', failed: 'Failed',
      needs_user: 'Input needed', error: 'Error',
    };
    badge.textContent = labels[state] || state;
  }

  _setInputEnabled(enabled) {
    this._userInput.disabled = !enabled;
    this._sendBtn.disabled   = !enabled;
    if (enabled) this._userInput.focus();
  }

  _showBanner(msg) {
    this._connBanner.textContent = msg;
    this._connBanner.style.display = 'block';
  }

  _hideBanner() {
    this._connBanner.style.display = 'none';
  }
}

// Boot when DOM is ready
document.addEventListener('DOMContentLoaded', async () => {
  const chat = new DesignChat();
  try {
    await chat.init();
  } catch (_) {
    // Banner already shown inside init()
  }
});
