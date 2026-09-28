"""
Lux - IKart's AI Shopping Assistant
Chatbot orchestrator; settings.AI_PROVIDER selects Groq (default) or Claude.
"""

import logging
from typing import Optional
from django.conf import settings
from .ai_providers import get_ai_provider
from .lux_context import customer_orders, relevant_products
from .lux_prompt import build_system_prompt

logger = logging.getLogger(__name__)

# The model sometimes emits zero-width spaces and non-breaking hyphens, which break the
# page paths the chat widget turns into links (e.g. "/\u200bproduct/nike\u2011air/").
# ZWJ/ZWNJ (U+200C/D) are kept: Indic scripts such as Hindi and Tamil need them.
_REPLY_CLEANUP = str.maketrans({
    "\u200b": None, "\u2060": None, "\ufeff": None,
    "\u2010": "-", "\u2011": "-",
})


class LuxChatbot:
    """Lux chatbot service - main orchestrator for customer interactions."""

    def __init__(self):
        """Initialize Lux with configured AI provider."""
        self.provider_name = getattr(settings, "AI_PROVIDER", "groq")
        self.provider = self._init_provider()

    def _init_provider(self):
        """Initialize the configured AI provider with its credentials."""
        if self.provider_name == "claude":
            api_key = getattr(settings, "CLAUDE_API_KEY", "")
            if not api_key:
                raise ValueError("CLAUDE_API_KEY not configured in settings")
            return get_ai_provider("claude", api_key=api_key, model=settings.CLAUDE_MODEL)

        elif self.provider_name == "groq":
            api_key = getattr(settings, "GROQ_API_KEY", "")
            if not api_key:
                raise ValueError("GROQ_API_KEY not configured in settings")
            return get_ai_provider("groq", api_key=api_key, model=settings.GROQ_MODEL)

        elif self.provider_name == "openai":
            api_key = getattr(settings, "OPENAI_API_KEY", "")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not configured in settings")
            return get_ai_provider("openai", api_key=api_key)

        elif self.provider_name == "ollama":
            base_url = getattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434")
            return get_ai_provider("ollama", base_url=base_url)

        else:
            raise ValueError(f"Unknown AI provider: {self.provider_name}")

    def chat(self, message: str, session_id: str, context: Optional[dict] = None) -> str:
        """
        Get Lux's response to a customer message.

        Args:
            message: Customer's message
            session_id: Unique conversation session ID
            context: Optional user context (username, order info, etc.)

        Returns:
            Lux's response text
        """
        # Validate input
        if not message or not message.strip():
            return "Hi! 👋 I'm Lux, your IKart shopping assistant. How can I help you today?"

        message = message.strip()[:1000]  # Max 1000 chars to prevent abuse

        # Get response from configured provider
        try:
            user = (context or {}).get("user")
            prompt = build_system_prompt(
                context, products=relevant_products(message), orders=customer_orders(user, message),
            )
            response = self.provider.get_response(prompt, message)
            return response.translate(_REPLY_CLEANUP) if response else "I'm thinking... Let me connect you with our support team instead."
        except Exception:
            # Graceful fallback for any provider errors
            logger.exception("Lux provider error")
            return "Oops! Something went wrong. Our support team would love to help: /support/"


# Global Lux instance (lazy initialization)
_lux_instance = None


def get_lux() -> LuxChatbot:
    """Get or create the Lux chatbot singleton."""
    global _lux_instance
    if _lux_instance is None:
        _lux_instance = LuxChatbot()
    return _lux_instance
