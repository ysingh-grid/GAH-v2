/**
 * GAH frontend — FAB overlay chat + ForgeCAD main view.
 *
 * WS protocol (server → client):
 *   thinking   — planner running; show typing indicator
 *   ask_user   — planner question; show as assistant bubble
 *   generating — geometry loop started; show ready banner
 *   success    — {forge_js, plan, run_id}; show output in main area
 *   needs_user — loop escalated; show as assistant bubble
 *   failed     — {category, message}; show error bubble
 *   error      — unexpected server exception
 *
 * All external API calls go to BACKEND_URL (default localhost:8001).
 * Set window.BACKEND_URL before this script loads to override.
 * Set window.FORGECAD_STUDIO_URL to embed the studio iframe instead of code view.
 */

const _BACKEND = window.BACKEND_URL || 'http://localhost:8001';

// ── Tiny HTML-safe formatter ──────────────────────────────────────────────────
function _fmt(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br>');
}

// ── DesignChat ────────────────────────────────────────────────────────────────
class DesignChat {
  constructor() {
    this._designId   = null;
    this._ws         = null;
    this._state      = 'idle'; // idle | connecting | ready | thinking | generating | done | failed
    this._forgeJs    = null;
    this._typingEl   = null;   // the current typing indicator DOM node
    this._panelOpen  = false;
    this._sessionStarted = false; // true after first POST /designs
  }

  // ── Panel open/close ────────────────────────────────────────────────────────

  toggleChat() {
    this._panelOpen = !this._panelOpen;
    const panel = document.getElementById('chat-panel');
    const fab   = document.getElementById('fab');

    panel.classList.toggle('open', this._panelOpen);
    fab.classList.toggle('open', this._panelOpen);

    if (this._panelOpen) {
      // Lazy-init session on first open
      if (!this._sessionStarted) {
        this._sessionStarted = true;
        this._boot();
      }
      // Focus input after slide-in animation
      setTimeout(() => {
        const inp = document.getElementById('chat-input');
        if (inp && !inp.disabled) inp.focus();
      }, 360);
      // Hide suggestions if user already sent messages
      const body = document.getElementById('chat-body');
      if (body && body.childElementCount > 2) {
        this._hideSuggestions();
      }
    }
  }

  // ── Boot: create backend session + connect WS ────────────────────────────────

  async _boot() {
    this._setConnDot('connecting');
    this._setInputEnabled(false);

    try {
      const resp = await fetch(`${_BACKEND}/designs`, { method: 'POST' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const body = await resp.json();
      this._designId = body.design_id;
    } catch (err) {
      this._showToast(`Cannot reach backend at ${_BACKEND} — is it running?`);
      this._setConnDot('error');
      return;
    }

    this._connectWs();
  }

  _connectWs() {
    const wsBase = _BACKEND.replace(/^http/, 'ws');
    this._ws = new WebSocket(`${wsBase}/designs/${this._designId}/chat`);

    this._ws.onopen = () => {
      this._state = 'ready';
      this._setConnDot('connected');
      this._setInputEnabled(true);
      this._hideToast();
    };

    this._ws.onmessage = (e) => {
      try { this._handleEvent(JSON.parse(e.data)); }
      catch (_) { /* ignore malformed frames */ }
    };

    this._ws.onerror = () => {
      this._showToast('WebSocket error — check backend logs.');
      this._setConnDot('error');
    };

    this._ws.onclose = (e) => {
      if (e.code !== 1000 && e.code !== 1005 && this._state !== 'done') {
        this._showToast('Connection closed. Refresh to reconnect.');
        this._setConnDot('error');
      }
    };
  }

  // ── Send ────────────────────────────────────────────────────────────────────

  sendChatMsg() {
    const inp  = document.getElementById('chat-input');
    const text = inp ? inp.value.trim() : '';
    if (!text) return;
    if (!this._ws || this._ws.readyState !== WebSocket.OPEN) return;
    if (this._state === 'thinking' || this._state === 'generating') return;

    this._ws.send(JSON.stringify({ type: 'message', text }));
    this._appendMsg('user', text);
    inp.value = '';
    inp.style.height = 'auto';
    this._setInputEnabled(false);
    this._hideSuggestions();
    this._showTyping();
  }

  // ── Incoming event handling ──────────────────────────────────────────────────

  _handleEvent(event) {
    switch (event.type) {

      case 'thinking':
        this._state = 'thinking';
        this._showTyping();
        break;

      case 'ask_user':
        this._state = 'ready';
        this._removeTyping();
        this._appendMsg('assistant', event.question, event.options || []);
        this._setInputEnabled(true);
        break;

      case 'generating':
        this._state = 'generating';
        this._removeTyping();
        this._showReadyBanner();
        // Don't re-enable input — generation is in progress
        break;

      case 'success':
        this._state = 'done';
        this._hideReadyBanner();
        this._removeTyping();
        this._forgeJs = event.forge_js || '';
        this._showOutput(event);
        // Show green dot on FAB (panel may be closed)
        document.getElementById('fab-dot').classList.add('visible');
        break;

      case 'needs_user':
        this._state = 'ready';
        this._hideReadyBanner();
        this._removeTyping();
        this._appendMsg('assistant', event.question || 'I need more information to continue.', event.options || []);
        this._setInputEnabled(true);
        break;

      case 'failed':
        this._state = 'failed';
        this._hideReadyBanner();
        this._removeTyping();
        this._appendMsg('system', `Generation failed [${event.category || 'unknown'}]: ${event.message || ''}`);
        this._setInputEnabled(true);
        break;

      case 'error':
        this._state = 'failed';
        this._hideReadyBanner();
        this._removeTyping();
        this._appendMsg('system', `Server error: ${event.message || 'unknown error'}`);
        this._setInputEnabled(true);
        break;
    }
  }

  // ── Output in main area ──────────────────────────────────────────────────────

  _showOutput(event) {
    const studioUrl = window.FORGECAD_STUDIO_URL;

    if (studioUrl && event.run_id) {
      // Load ForgeCAD studio iframe
      document.getElementById('hero-view').style.display = 'none';
      const studioView = document.getElementById('studio-view');
      studioView.style.display = 'block';
      document.getElementById('forge-iframe').src = `${studioUrl}?run_id=${event.run_id}`;
    } else {
      // Show .forge.js code view
      document.getElementById('hero-view').style.display = 'none';
      const codeView = document.getElementById('code-view');
      codeView.style.display = 'flex';
      const pre = document.getElementById('forge-code');
      pre.textContent = event.forge_js || '// (no forge script returned)';
    }

    // Append summary bubble in chat
    const plan = event.plan;
    if (plan && plan.steps && plan.steps.length) {
      const rows = plan.steps.map(s =>
        `<tr><td>${s.id}</td><td>${s.primitive}</td></tr>`
      ).join('');
      const table = `<table><tr><td colspan="2" style="color:var(--green);padding-bottom:6px">✓ Part generated (${plan.steps.length} step${plan.steps.length !== 1 ? 's' : ''})</td></tr>${rows}</table>`;
      this._appendRaw('msg-summary', table);
    } else {
      this._appendMsg('assistant', `✓ Part generated! Open the code view to see .forge.js`);
    }
  }

  // ── DOM helpers ──────────────────────────────────────────────────────────────

  _appendMsg(role, text, options = []) {
    const body = document.getElementById('chat-body');
    if (!body) return;

    const row = document.createElement('div');
    row.className = `msg ${role}`;

    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    bubble.innerHTML = _fmt(text);
    row.appendChild(bubble);

    if (options.length) {
      const optRow = document.createElement('div');
      optRow.className = 'msg-options';
      options.forEach(opt => {
        const btn = document.createElement('button');
        btn.className = 'opt-btn';
        btn.textContent = opt;
        btn.addEventListener('click', () => {
          const inp = document.getElementById('chat-input');
          if (inp) inp.value = opt;
          this.sendChatMsg();
        });
        optRow.appendChild(btn);
      });
      row.appendChild(optRow);
    }

    body.appendChild(row);
    body.scrollTop = body.scrollHeight;
  }

  _appendRaw(extraClass, html) {
    const body = document.getElementById('chat-body');
    if (!body) return;
    const row = document.createElement('div');
    row.className = `msg assistant ${extraClass}`;
    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    bubble.innerHTML = html;
    row.appendChild(bubble);
    body.appendChild(row);
    body.scrollTop = body.scrollHeight;
  }

  _showTyping() {
    if (this._typingEl) return; // already showing
    const body = document.getElementById('chat-body');
    if (!body) return;

    const row = document.createElement('div');
    row.className = 'msg assistant';
    const ind = document.createElement('div');
    ind.className = 'typing-indicator';
    ind.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';
    row.appendChild(ind);
    body.appendChild(row);
    this._typingEl = row;
    body.scrollTop = body.scrollHeight;
  }

  _removeTyping() {
    if (this._typingEl) {
      this._typingEl.remove();
      this._typingEl = null;
    }
  }

  _showReadyBanner() {
    const banner = document.getElementById('ready-banner');
    if (banner) banner.classList.add('visible');
  }

  _hideReadyBanner() {
    const banner = document.getElementById('ready-banner');
    if (banner) banner.classList.remove('visible');
  }

  _hideSuggestions() {
    const s = document.getElementById('chat-suggestions');
    if (s) s.style.display = 'none';
  }

  _setInputEnabled(enabled) {
    const inp = document.getElementById('chat-input');
    const btn = document.getElementById('send-btn');
    if (inp) inp.disabled = !enabled;
    if (btn) btn.disabled = !enabled;
  }

  _setConnDot(state) {
    const dot = document.getElementById('conn-dot');
    if (!dot) return;
    dot.className = `header-dot ${state}`;
    dot.title = state;
  }

  _showToast(msg) {
    const t = document.getElementById('conn-toast');
    if (!t) return;
    t.textContent = msg;
    t.style.display = 'block';
  }

  _hideToast() {
    const t = document.getElementById('conn-toast');
    if (t) t.style.display = 'none';
  }

  // ── Public helpers exposed on window.__gah ───────────────────────────────────

  copyCode() {
    const pre = document.getElementById('forge-code');
    if (!pre || !pre.textContent) return;
    navigator.clipboard.writeText(pre.textContent).then(() => {
      const btn = document.getElementById('copy-btn');
      if (btn) {
        const orig = btn.textContent;
        btn.textContent = 'Copied!';
        setTimeout(() => { btn.textContent = orig; }, 1500);
      }
    });
  }

  autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 100) + 'px';
  }

  handleKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      this.sendChatMsg();
    }
  }

  useSuggestion(btn) {
    const inp = document.getElementById('chat-input');
    if (!inp) return;
    inp.value = btn.textContent.trim();
    // If panel not open yet, open it first (will trigger boot)
    if (!this._panelOpen) {
      this.toggleChat();
      // Wait for boot then send
      const check = setInterval(() => {
        if (this._ws && this._ws.readyState === WebSocket.OPEN) {
          clearInterval(check);
          this.sendChatMsg();
        }
      }, 100);
    } else {
      this.sendChatMsg();
    }
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const chat = new DesignChat();

  // Add connection error toast element if not in HTML already
  if (!document.getElementById('conn-toast')) {
    const toast = document.createElement('div');
    toast.id = 'conn-toast';
    document.body.appendChild(toast);
  }

  // Expose public interface
  window.__gah = {
    toggleChat:    () => chat.toggleChat(),
    sendChatMsg:   () => chat.sendChatMsg(),
    useSuggestion: (btn) => chat.useSuggestion(btn),
    autoResize:    (el)  => chat.autoResize(el),
    handleKey:     (e)   => chat.handleKey(e),
    copyCode:      () => chat.copyCode(),
  };
});
