/**
 * Lux - IKart's AI Shopping Assistant
 * Vanilla JavaScript chatbot widget with smooth animations and mobile responsiveness
 */

class LuxChatbot {
  constructor() {
    this.sessionId = this.getOrCreateSessionId();
    this.isOpen = false;
    this.isLoading = false;
    this.messages = [];
    this.init();
  }

  getOrCreateSessionId() {
    let sessionId = sessionStorage.getItem('lux_session_id');
    if (!sessionId) {
      sessionId = 'session_' + Math.random().toString(36).substr(2, 9);
      sessionStorage.setItem('lux_session_id', sessionId);
    }
    return sessionId;
  }

  init() {
    this.createWidget();
    this.attachEventListeners();
  }

  createWidget() {
    const widget = document.createElement('div');
    widget.id = 'lux-widget';
    widget.innerHTML = `
      <div id="lux-button" class="lux-button" title="Chat with Lux">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
        </svg>
        <span class="lux-badge" id="lux-badge" style="display: none;">1</span>
      </div>
      <div id="lux-panel" class="lux-panel">
        <div class="lux-header">
          <div class="lux-title">
            <span>Lux</span>
            <span class="lux-subtitle">IKart Assistant</span>
          </div>
          <button id="lux-close" class="lux-close" title="Close">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
        <div id="lux-messages" class="lux-messages">
          <div class="lux-message lux-message-bot">
            <div class="lux-message-content">Hi! 👋 I'm Lux, your IKart shopping assistant. How can I help you today?</div>
          </div>
        </div>
        <div class="lux-suggestions" id="lux-suggestions">
          <button class="lux-suggestion" data-message="Track my order">Track order</button>
          <button class="lux-suggestion" data-message="Tell me about returns">Returns</button>
          <button class="lux-suggestion" data-message="Size guide">Size guide</button>
        </div>
        <div class="lux-input-area">
          <input
            id="lux-input"
            type="text"
            class="lux-input"
            placeholder="Type your question..."
            autocomplete="off"
          />
          <button id="lux-send" class="lux-send" title="Send">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="22" y1="2" x2="11" y2="13"></line>
              <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
            </svg>
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(widget);
  }

  attachEventListeners() {
    const button = document.getElementById('lux-button');
    const closeBtn = document.getElementById('lux-close');
    const sendBtn = document.getElementById('lux-send');
    const input = document.getElementById('lux-input');
    const suggestions = document.querySelectorAll('.lux-suggestion');

    button.addEventListener('click', () => this.toggle());
    closeBtn.addEventListener('click', () => this.toggle());
    sendBtn.addEventListener('click', () => this.sendMessage());
    input.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') this.sendMessage();
    });

    suggestions.forEach(btn => {
      btn.addEventListener('click', (e) => {
        const message = e.target.dataset.message;
        input.value = message;
        this.sendMessage();
      });
    });
  }

  toggle() {
    const panel = document.getElementById('lux-panel');
    const button = document.getElementById('lux-button');
    this.isOpen = !this.isOpen;

    if (this.isOpen) {
      panel.classList.add('lux-open');
      button.classList.add('lux-button-open');
      document.getElementById('lux-input').focus();
    } else {
      panel.classList.remove('lux-open');
      button.classList.remove('lux-button-open');
    }
  }

  async sendMessage() {
    const input = document.getElementById('lux-input');
    const message = input.value.trim();

    if (!message || this.isLoading) return;

    input.value = '';
    this.addMessage('user', message);
    this.isLoading = true;
    this.showTypingIndicator();

    try {
      const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
      const response = await fetch('/chat/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({
          message,
          session_id: this.sessionId,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
      this.removeTypingIndicator();

      if (data.error) {
        this.addMessage('bot', 'Oops! Something went wrong. Try again?');
      } else {
        this.addMessage('bot', data.reply);
        this.updateSessionId(data.session_id);
      }
    } catch (error) {
      console.error('Lux error:', error);
      this.removeTypingIndicator();
      this.addMessage('bot', 'I'm having trouble connecting. Please try again or contact support.');
    } finally {
      this.isLoading = false;
      document.getElementById('lux-input').focus();
    }
  }

  addMessage(role, text) {
    const messagesContainer = document.getElementById('lux-messages');
    const message = document.createElement('div');
    const className = role === 'user' ? 'lux-message-user' : 'lux-message-bot';

    message.className = `lux-message ${className}`;
    message.innerHTML = `<div class="lux-message-content">${this.escapeHtml(text)}</div>`;

    messagesContainer.appendChild(message);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    if (role === 'bot') {
      document.getElementById('lux-suggestions').style.display = 'none';
    }
  }

  showTypingIndicator() {
    const messagesContainer = document.getElementById('lux-messages');
    const typing = document.createElement('div');
    typing.id = 'lux-typing';
    typing.className = 'lux-message lux-message-bot';
    typing.innerHTML = `
      <div class="lux-message-content">
        <div class="lux-typing-dots">
          <span></span><span></span><span></span>
        </div>
      </div>
    `;
    messagesContainer.appendChild(typing);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  removeTypingIndicator() {
    const typing = document.getElementById('lux-typing');
    if (typing) typing.remove();
  }

  updateSessionId(newId) {
    this.sessionId = newId;
    sessionStorage.setItem('lux_session_id', newId);
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}

// Initialize Lux when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    window.lux = new LuxChatbot();
  });
} else {
  window.lux = new LuxChatbot();
}
