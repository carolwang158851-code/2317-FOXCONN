"""Provider-neutral interfaces; no OpenAI SDK or network implementation."""

from .client_interface import MockOpenAIClient, OpenAIClientInterface

__all__ = ["MockOpenAIClient", "OpenAIClientInterface"]
