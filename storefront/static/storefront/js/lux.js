class LuxChatbot {
  constructor() {
    this.init();
  }

  init() {
    const widget = document.createElement('div');
    widget.id = 'lux-widget';
    widget.style.cssText = 'position: fixed; bottom: 20px; right: 20px; width: 60px; height: 60px; background: #FF6B35; border-radius: 50%; cursor: pointer; display: flex; align-items: center; justify-content: center; color: white; font-size: 28px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); z-index: 9999;';
    widget.textContent = 'Chat';
    widget.addEventListener('click', () => alert('Lux Chat - Coming Soon'));
    document.body.appendChild(widget);
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    window.lux = new LuxChatbot();
  });
} else {
  window.lux = new LuxChatbot();
}
