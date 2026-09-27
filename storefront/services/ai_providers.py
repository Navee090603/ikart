"""
Abstract AI provider interface and concrete implementations for Lux chatbot.
Allows swapping between Claude API, OpenAI, Ollama, etc. without code changes.
"""

from abc import ABC, abstractmethod
from typing import Optional
import anthropic
import requests
import logging

logger = logging.getLogger(__name__)


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


class GroqProvider(AIProvider):
    """Groq Cloud API implementation - fast inference, free tier available."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
        self.model = "mixtral-8x7b-32768"

    def get_response(self, message: str, session_id: str, context: Optional[dict] = None) -> str:
        """Get response from Groq API."""
        if not self.api_key:
            logger.error("Groq API key not configured")
            return "Groq API key is not configured. Please contact support."

        system_prompt = self._build_system_prompt(context)

        try:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message}
                ],
                "max_tokens": 500,
                "temperature": 0.7
            }

            logger.info(f"Groq API call: model={self.model}, url={self.api_url}")

            response = requests.post(
                self.api_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=10
            )

            logger.info(f"Groq response status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                result = data["choices"][0]["message"]["content"]
                logger.info(f"Groq success: {result[:50]}...")
                return result
            elif response.status_code == 401:
                error_text = response.text
                logger.error(f"Groq authentication failed: {error_text}")
                return "Groq API key is invalid or expired."
            elif response.status_code == 429:
                logger.warning("Groq rate limit exceeded")
                return "I'm experiencing high demand. Please try again in a moment!"
            elif response.status_code == 400:
                error_text = response.text
                logger.error(f"Groq bad request (400): {error_text}")
                return f"Invalid request to Groq. Error: {error_text[:100]}"
            else:
                error_text = response.text
                logger.error(f"Groq API error {response.status_code}: {error_text}")
                return f"Groq API error {response.status_code}: {error_text[:100]}"

        except requests.exceptions.Timeout:
            logger.error("Groq API request timed out")
            return "Request timed out. Groq server is slow. Please try again."
        except requests.exceptions.RequestException as e:
            logger.exception(f"Groq API request failed: {str(e)}")
            return f"Connection failed: {str(e)[:100]}"
        except Exception as e:
            logger.exception(f"Groq provider error: {str(e)}")
            return f"Error: {str(e)[:100]}"

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
        "groq": GroqProvider,
        "openai": OpenAIProvider,
        "ollama": OllamaProvider,
    }

    if provider_name not in providers:
        raise ValueError(f"Unknown provider: {provider_name}. Must be one of {list(providers.keys())}")

    return providers[provider_name](**kwargs)
