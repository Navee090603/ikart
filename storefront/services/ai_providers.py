"""
Abstract AI provider interface and concrete implementations for Lux chatbot.
Allows swapping between Claude API, Groq, OpenAI, Ollama, etc. without code changes.
"""

from abc import ABC, abstractmethod
import logging

import anthropic
import requests

logger = logging.getLogger(__name__)

UNAVAILABLE = "I'm temporarily unavailable. Our support team is here to help: /support/"
BUSY = "I'm experiencing high demand right now. Please try again in a moment!"


class AIProvider(ABC):
    """Abstract base class for AI providers."""

    @abstractmethod
    def get_response(self, system_prompt: str, message: str) -> str:
        """Return the model's reply to `message` under `system_prompt`."""


class ClaudeProvider(AIProvider):
    """Anthropic Claude API implementation."""

    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = "claude-3-5-sonnet-20241022"

    def get_response(self, system_prompt: str, message: str) -> str:
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                system=system_prompt,
                messages=[{"role": "user", "content": message}],
            )
            return response.content[0].text
        except anthropic.RateLimitError:
            return BUSY
        except anthropic.APIError:
            logger.exception("Claude API error")
            return UNAVAILABLE


class GroqProvider(AIProvider):
    """Groq Cloud API implementation - fast inference, free tier available."""

    def __init__(self, api_key: str, model: str = "openai/gpt-oss-20b"):
        self.api_key = api_key
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
        self.model = model

    def get_response(self, system_prompt: str, message: str) -> str:
        try:
            response = requests.post(
                self.api_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message},
                    ],
                    # gpt-oss models spend part of this budget on hidden reasoning tokens.
                    "max_tokens": 1024,
                    "temperature": 0.3,
                },
                timeout=20,
            )
        except requests.exceptions.RequestException:
            logger.exception("Groq API request failed")
            return UNAVAILABLE

        if response.status_code == 429:
            logger.warning("Groq rate limit exceeded")
            return BUSY
        if response.status_code != 200:
            logger.error("Groq API error %s: %s", response.status_code, response.text[:500])
            return UNAVAILABLE

        content = response.json()["choices"][0]["message"].get("content") or ""
        return content.strip() or UNAVAILABLE


class OpenAIProvider(AIProvider):
    """OpenAI ChatGPT implementation (stub for future migration)."""

    def __init__(self, api_key: str):
        raise NotImplementedError("OpenAI provider not yet implemented.")

    def get_response(self, system_prompt: str, message: str) -> str:
        raise NotImplementedError


class OllamaProvider(AIProvider):
    """Local Ollama implementation for self-hosted LLM (stub for future migration)."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        raise NotImplementedError("Ollama provider not yet implemented.")

    def get_response(self, system_prompt: str, message: str) -> str:
        raise NotImplementedError


def get_ai_provider(provider_name: str, **kwargs) -> AIProvider:
    """Instantiate the provider named by AI_PROVIDER with its credentials."""
    providers = {
        "claude": ClaudeProvider,
        "groq": GroqProvider,
        "openai": OpenAIProvider,
        "ollama": OllamaProvider,
    }
    if provider_name not in providers:
        raise ValueError(f"Unknown provider: {provider_name}. Must be one of {list(providers)}")
    return providers[provider_name](**kwargs)
