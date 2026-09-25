"""
Abstract AI provider interface and concrete implementations for Lux chatbot.
Allows swapping between Claude API, OpenAI, Ollama, etc. without code changes.
"""

from abc import ABC, abstractmethod
from typing import Optional
import anthropic


class AIProvider(ABC):
    """Abstract base class for AI providers."""

    @abstractmethod
    def get_response(self, message: str, session_id: str, context: Optional[dict] = None) -> str:
        """
        Get a response from the AI model.

        Args:
            message: User's message
            session_id: Conversation session ID
            context: Optional user/session context (e.g., username, order history)

        Returns:
            AI model's response text
        """
        pass


class ClaudeProvider(AIProvider):
    """Anthropic Claude API implementation."""

    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = "claude-3-5-sonnet-20241022"

    def get_response(self, message: str, session_id: str, context: Optional[dict] = None) -> str:
        """Get response from Claude API."""
        # Build system prompt with store context
        system_prompt = self._build_system_prompt(context)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": message}
                ]
            )
            return response.content[0].text
        except anthropic.APIError as e:
            # Graceful error handling
            if "rate_limit" in str(e).lower():
                return "I'm experiencing high demand right now. Please try again in a moment!"
            elif "401" in str(e) or "auth" in str(e).lower():
                return "I encountered an authentication issue. Please contact support."
            else:
                return "I'm temporarily unavailable. Our support team is here to help: /support/"

    def _build_system_prompt(self, context: Optional[dict] = None) -> str:
        """Build Lux system prompt with optional user context."""
        base_prompt = """You are Lux, IKart's intelligent shopping assistant. Your mission is to make
shopping delightful, fast, and worry-free.

PERSONALITY:
- Warm and professional
- Concise (2-3 sentences per response max)
- Proactive (anticipate customer needs)
- Honest (admit when unsure, offer escalation)

CORE POLICIES TO REMEMBER:
- 30-day returns: No questions asked, full refund
- Shipping: Standard and Express options available
- Payment: Razorpay secure checkout (SSL encrypted)
- Quality: All products curated for durability & style
- Support hours: 24/7 automated, human support available

WHAT YOU CAN DO:
✓ Recommend products based on customer preferences
✓ Answer questions about sizing, materials, fit
✓ Help with checkout, payment, orders
✓ Track orders (if customer is logged in)
✓ Explain policies, returns, shipping
✓ Suggest support escalation when needed

WHAT YOU CANNOT DO:
✗ Create new orders on behalf of customer
✗ Process refunds directly (suggest support)
✗ Access payment details or sensitive information
✗ Make up product features or policies

IF UNSURE:
- Say "I'm not certain, but our support team can help"
- Suggest: Contact our support team at /support/
- Always maintain customer trust"""

        # Personalize if user is logged in
        if context and "username" in context:
            username = context["username"]
            if username:
                base_prompt += f"\n\nCUSTOMER CONTEXT:\nThis customer's name is {username}. Use their name for personalization when appropriate."

        return base_prompt


class OpenAIProvider(AIProvider):
    """OpenAI ChatGPT implementation (stub for future migration)."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        # Future: implement with openai package
        raise NotImplementedError("OpenAI provider not yet implemented. Coming soon!")

    def get_response(self, message: str, session_id: str, context: Optional[dict] = None) -> str:
        """Get response from OpenAI API."""
        pass


class OllamaProvider(AIProvider):
    """Local Ollama implementation for self-hosted LLM (stub for future migration)."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        self.model = "llama2"  # Default model, configurable
        # Future: implement with requests to Ollama API
        raise NotImplementedError("Ollama provider not yet implemented. Coming soon!")

    def get_response(self, message: str, session_id: str, context: Optional[dict] = None) -> str:
        """Get response from local Ollama model."""
        pass


def get_ai_provider(provider_name: str, **kwargs) -> AIProvider:
    """
    Factory function to instantiate the correct AI provider.

    Args:
        provider_name: Name of provider ('claude', 'openai', 'ollama')
        **kwargs: Provider-specific arguments (api_key, base_url, etc.)

    Returns:
        Instantiated AIProvider subclass
    """
    providers = {
        "claude": ClaudeProvider,
        "openai": OpenAIProvider,
        "ollama": OllamaProvider,
    }

    if provider_name not in providers:
        raise ValueError(f"Unknown provider: {provider_name}. Must be one of {list(providers.keys())}")

    return providers[provider_name](**kwargs)
