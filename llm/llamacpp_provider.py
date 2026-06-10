from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel
from llm.base import LLMProvider
from config import settings


class LlamaCppProvider(LLMProvider):
    """
    Calls a running llama-server instance over HTTP.
    llama-server exposes a fully OpenAI-compatible REST API — so we
    just point ChatOpenAI at it with a custom base_url. No Python
    bindings, no C++ compilation, no llama-cpp-python in the project.
    """

    def get_chat_model(self) -> BaseChatModel:
        return ChatOpenAI(
            base_url=settings.llamacpp_base_url,   # e.g. http://localhost:8081/v1
            api_key="not-required",                 # llama-server has no auth by default
            model=settings.llamacpp_model_name,
            temperature=0.3,
            max_tokens=1024,
            streaming=True,
        )

    def get_provider_name(self) -> str:
        return f"llama-server @ {settings.llamacpp_base_url}"
