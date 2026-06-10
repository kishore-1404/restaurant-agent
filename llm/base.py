from abc import ABC, abstractmethod
from langchain_core.language_models import BaseChatModel


class LLMProvider(ABC):
    """
    Abstract base — all providers expose the same interface.
    LangGraph only ever sees a BaseChatModel, never a specific provider.
    """

    @abstractmethod
    def get_chat_model(self) -> BaseChatModel:
        """Return a LangChain-compatible chat model with tool-calling support."""
        ...

    @abstractmethod
    def get_provider_name(self) -> str:
        ...

    def supports_streaming(self) -> bool:
        return True
