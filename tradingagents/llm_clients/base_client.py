from abc import ABC, abstractmethod
from typing import Any, Optional
import warnings


def normalize_content(response):
    """Normalize LLM response content to a plain string.

    Multiple providers (OpenAI Responses API, Google Gemini 3, DeepSeek) return
    content as a list of typed blocks, e.g. [{'type': 'reasoning', ...}, {'type': 'text', 'text': '...'}].
    Downstream agents expect response.content to be a string. This extracts
    and joins the text blocks while discarding reasoning/metadata blocks.

    IMPORTANT: Reasoning content is preserved in response.additional_kwargs so
    it can be passed back to the API on subsequent turns. DeepSeek's thinking
    mode (V4 Pro, V4 Flash, deepseek-reasoner) requires reasoning_content to
    be included when assistant messages are sent back in multi-turn calls.
    """
    content = response.content
    if isinstance(content, list):
        texts = []
        reasoning_parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "reasoning":
                    reasoning_parts.append(item.get("text", ""))
                elif item.get("type") == "text":
                    texts.append(item.get("text", ""))
            elif isinstance(item, str):
                texts.append(item)

        # Preserve reasoning content so DeepSeek's thinking mode can
        # receive it back on subsequent API calls in multi-turn pipelines.
        if reasoning_parts:
            if response.additional_kwargs is None:
                response.additional_kwargs = {}
            response.additional_kwargs["reasoning_content"] = "\n".join(reasoning_parts)

        response.content = "\n".join(t for t in texts if t)
    return response


class BaseLLMClient(ABC):
    """Abstract base class for LLM clients."""

    def __init__(self, model: str, base_url: Optional[str] = None, **kwargs):
        self.model = model
        self.base_url = base_url
        self.kwargs = kwargs

    def get_provider_name(self) -> str:
        """Return the provider name used in warning messages."""
        provider = getattr(self, "provider", None)
        if provider:
            return str(provider)
        return self.__class__.__name__.removesuffix("Client").lower()

    def warn_if_unknown_model(self) -> None:
        """Warn when the model is outside the known list for the provider."""
        if self.validate_model():
            return

        warnings.warn(
            (
                f"Model '{self.model}' is not in the known model list for "
                f"provider '{self.get_provider_name()}'. Continuing anyway."
            ),
            RuntimeWarning,
            stacklevel=2,
        )

    @abstractmethod
    def get_llm(self) -> Any:
        """Return the configured LLM instance."""
        pass

    @abstractmethod
    def validate_model(self) -> bool:
        """Validate that the model is supported by this client."""
        pass
