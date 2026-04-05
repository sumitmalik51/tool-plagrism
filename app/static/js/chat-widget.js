/* ═══════════════════════════════════════════════════════════
   PlagiarismGuard Chat Widget — Floating support chatbot
   Drop <script src="/static/js/chat-widget.js"></script> on any page.
   ═══════════════════════════════════════════════════════════ */
(function () {
  'use strict';
  if (document.getElementById('pg-chat-fab')) return;

  // --- Styles ---
  var style = document.createElement('style');
  style.textContent = `
    #pg-chat-fab {
      position: fixed; bottom: 24px; right: 24px; z-index: 9999;
      width: 56px; height: 56px; border-radius: 50%;
      background: linear-gradient(135deg, #6c5ce7, #5a4bd1);
      color: #fff; border: none; cursor: pointer;
      box-shadow: 0 6px 24px rgba(108,92,231,0.35);
      display: flex; align-items: center; justify-content: center;
      transition: transform 0.2s, box-shadow 0.2s;
    }
    #pg-chat-fab:hover { transform: scale(1.08); box-shadow: 0 8px 32px rgba(108,92,231,0.45); }
    #pg-chat-fab svg { width: 26px; height: 26px; }
    #pg-chat-fab .close-icon { display: none; }
    #pg-chat-fab.open .chat-icon { display: none; }
    #pg-chat-fab.open .close-icon { display: block; }

    #pg-chat-panel {
      position: fixed; bottom: 92px; right: 24px; z-index: 9998;
      width: 380px; max-width: calc(100vw - 32px);
      height: 520px; max-height: calc(100vh - 120px);
      border-radius: 20px; overflow: hidden;
      display: none; flex-direction: column;
      box-shadow: 0 16px 64px rgba(0,0,0,0.35);
      animation: pgChatSlideUp 0.3s ease;
    }
    #pg-chat-panel.open { display: flex; }
    @keyframes pgChatSlideUp {
      from { opacity: 0; transform: translateY(20px); }
      to { opacity: 1; transform: translateY(0); }
    }

    /* Dark theme (default) */
    #pg-chat-panel {
      background: #0f172a; border: 1px solid #1e293b; color: #e2e8f0;
    }
    #pg-chat-header {
      padding: 16px 20px; background: linear-gradient(135deg, #6c5ce7, #5a4bd1);
      display: flex; align-items: center; gap: 12px; flex-shrink: 0;
    }
    #pg-chat-header .avatar {
      width: 36px; height: 36px; border-radius: 50%; background: rgba(255,255,255,0.2);
      display: flex; align-items: center; justify-content: center; font-size: 18px;
    }
    #pg-chat-header .info h3 { font-size: 14px; font-weight: 700; color: #fff; margin: 0; }
    #pg-chat-header .info p { font-size: 11px; color: rgba(255,255,255,0.7); margin: 2px 0 0; }

    #pg-chat-messages {
      flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px;
      scrollbar-width: thin; scrollbar-color: #334155 transparent;
    }
    #pg-chat-messages::-webkit-scrollbar { width: 5px; }
    #pg-chat-messages::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }

    .pg-msg {
      max-width: 85%; padding: 10px 14px; border-radius: 16px;
      font-size: 13px; line-height: 1.55; word-wrap: break-word;
    }
    .pg-msg.bot {
      background: #1e293b; color: #e2e8f0; align-self: flex-start;
      border-bottom-left-radius: 4px;
    }
    .pg-msg.user {
      background: #6c5ce7; color: #fff; align-self: flex-end;
      border-bottom-right-radius: 4px;
    }
    .pg-msg.typing {
      background: #1e293b; color: #64748b; align-self: flex-start;
      border-bottom-left-radius: 4px; font-style: italic;
    }

    .pg-suggestions {
      display: flex; flex-wrap: wrap; gap: 6px; padding: 0 16px 8px;
    }
    .pg-suggestion-chip {
      padding: 6px 12px; border-radius: 20px; font-size: 12px;
      background: #1e293b; border: 1px solid #334155; color: #94a3b8;
      cursor: pointer; transition: all 0.15s; white-space: nowrap;
    }
    .pg-suggestion-chip:hover { border-color: #6c5ce7; color: #e2e8f0; background: #6c5ce7/10; }

    #pg-chat-input-area {
      padding: 12px 16px; border-top: 1px solid #1e293b; display: flex; gap: 8px; flex-shrink: 0;
    }
    #pg-chat-input {
      flex: 1; padding: 10px 14px; border-radius: 12px;
      background: #1e293b; border: 1px solid #334155; color: #e2e8f0;
      font-size: 13px; outline: none; transition: border-color 0.2s;
    }
    #pg-chat-input:focus { border-color: #6c5ce7; }
    #pg-chat-input::placeholder { color: #4a5568; }
    #pg-chat-send {
      width: 40px; height: 40px; border-radius: 12px; border: none;
      background: #6c5ce7; color: #fff; cursor: pointer;
      display: flex; align-items: center; justify-content: center;
      transition: background 0.15s;
    }
    #pg-chat-send:hover { background: #5a4bd1; }
    #pg-chat-send:disabled { opacity: 0.4; cursor: not-allowed; }
    #pg-chat-send svg { width: 18px; height: 18px; }

    /* Light theme support */
    html.light #pg-chat-panel { background: #fff; border-color: #e2e8f0; color: #1a202c; }
    html.light .pg-msg.bot { background: #f1f5f9; color: #1a202c; }
    html.light .pg-msg.typing { background: #f1f5f9; color: #94a3b8; }
    html.light #pg-chat-input { background: #f8fafc; border-color: #e2e8f0; color: #1a202c; }
    html.light #pg-chat-input::placeholder { color: #94a3b8; }
    html.light #pg-chat-messages::-webkit-scrollbar-thumb { background: #cbd5e1; }
    html.light .pg-suggestion-chip { background: #f1f5f9; border-color: #e2e8f0; color: #475569; }
    html.light #pg-chat-input-area { border-color: #e2e8f0; }
  `;
  document.head.appendChild(style);

  // --- FAB Button ---
  var fab = document.createElement('button');
  fab.id = 'pg-chat-fab';
  fab.setAttribute('aria-label', 'Open support chat');
  fab.innerHTML = '<svg class="chat-icon" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>'
    + '<svg class="close-icon" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M18 6L6 18M6 6l12 12"/></svg>';
  document.body.appendChild(fab);

  // --- Chat Panel ---
  var panel = document.createElement('div');
  panel.id = 'pg-chat-panel';
  panel.innerHTML = `
    <div id="pg-chat-header">
      <div class="avatar">🤖</div>
      <div class="info">
        <h3>PlagiarismGuard Assistant</h3>
        <p>Ask me anything about the platform</p>
      </div>
    </div>
    <div id="pg-chat-messages"></div>
    <div class="pg-suggestions" id="pg-chat-suggestions">
      <button class="pg-suggestion-chip" data-q="What features do you offer?">Features</button>
      <button class="pg-suggestion-chip" data-q="What are the pricing plans?">Pricing</button>
      <button class="pg-suggestion-chip" data-q="How does plagiarism detection work?">How it works</button>
      <button class="pg-suggestion-chip" data-q="What file formats are supported?">File formats</button>
      <button class="pg-suggestion-chip" data-q="Do you have an API?">API access</button>
    </div>
    <div id="pg-chat-input-area">
      <input id="pg-chat-input" type="text" placeholder="Ask about PlagiarismGuard..." maxlength="500" autocomplete="off" />
      <button id="pg-chat-send" aria-label="Send">
        <svg fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/></svg>
      </button>
    </div>
  `;
  document.body.appendChild(panel);

  // --- State ---
  var messages = []; // { role, content }
  var isOpen = false;
  var isSending = false;

  var msgContainer = document.getElementById('pg-chat-messages');
  var input = document.getElementById('pg-chat-input');
  var sendBtn = document.getElementById('pg-chat-send');
  var suggestions = document.getElementById('pg-chat-suggestions');

  // Welcome message
  addBotMessage("👋 Hi! I'm the PlagiarismGuard Assistant. Ask me anything about our platform — features, pricing, how things work, or troubleshooting!");

  // --- Toggle ---
  fab.addEventListener('click', function () {
    isOpen = !isOpen;
    fab.classList.toggle('open', isOpen);
    panel.classList.toggle('open', isOpen);
    if (isOpen) input.focus();
  });

  // --- Suggestion chips ---
  suggestions.addEventListener('click', function (e) {
    var chip = e.target.closest('.pg-suggestion-chip');
    if (!chip) return;
    var q = chip.getAttribute('data-q');
    if (q) sendMessage(q);
  });

  // --- Send ---
  sendBtn.addEventListener('click', function () {
    var text = input.value.trim();
    if (text) sendMessage(text);
  });

  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      var text = input.value.trim();
      if (text) sendMessage(text);
    }
  });

  function sendMessage(text) {
    if (isSending) return;
    input.value = '';
    suggestions.style.display = 'none';

    // Add user message
    messages.push({ role: 'user', content: text });
    addUserMessage(text);

    // Show typing indicator
    var typingEl = addTypingIndicator();
    isSending = true;
    sendBtn.disabled = true;

    fetch('/api/v1/chatbot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: messages.slice(-10) })
    })
      .then(function (r) {
        if (!r.ok) throw new Error('Failed');
        return r.json();
      })
      .then(function (data) {
        typingEl.remove();
        var reply = data.reply || "Sorry, I couldn't process that. Please try again.";
        messages.push({ role: 'assistant', content: reply });
        addBotMessage(reply);
      })
      .catch(function () {
        typingEl.remove();
        addBotMessage("⚠️ Sorry, I'm having trouble connecting. Please try again in a moment.");
      })
      .finally(function () {
        isSending = false;
        sendBtn.disabled = false;
        input.focus();
      });
  }

  // --- DOM helpers ---
  function addUserMessage(text) {
    var el = document.createElement('div');
    el.className = 'pg-msg user';
    el.textContent = text;
    msgContainer.appendChild(el);
    scrollToBottom();
  }

  function addBotMessage(text) {
    var el = document.createElement('div');
    el.className = 'pg-msg bot';
    // Extract markdown links before HTML-escaping so they don't get mangled
    var links = [];
    var processed = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function(match, label, url) {
      var idx = links.length;
      links.push({ label: label, url: url });
      return '%%PGLINK' + idx + '%%';
    });
    // HTML escape
    processed = processed
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    // Restore links as clickable <a> tags
    processed = processed.replace(/%%PGLINK(\d+)%%/g, function(m, i) {
      var lk = links[parseInt(i)];
      return '<a href="' + lk.url + '" style="color:#818cf8;text-decoration:underline;font-weight:500" target="_top">' + lk.label + '</a>';
    });
    // Bold and newlines
    processed = processed
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\n/g, '<br>');
    el.innerHTML = processed;
    msgContainer.appendChild(el);
    scrollToBottom();
  }

  function addTypingIndicator() {
    var el = document.createElement('div');
    el.className = 'pg-msg typing';
    el.textContent = 'Thinking...';
    msgContainer.appendChild(el);
    scrollToBottom();
    return el;
  }

  function scrollToBottom() {
    requestAnimationFrame(function () {
      msgContainer.scrollTop = msgContainer.scrollHeight;
    });
  }
})();
