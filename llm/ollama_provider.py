from langchain_ollama import ChatOllama
from langchain_core.language_models import BaseChatModel
from llm.base import LLMProvider
from config import settings


class OllamaProvider(LLMProvider):
    """
    Local inference via Ollama.
    Requires Ollama running: https://ollama.ai
    Pull a model first: ollama pull llama3.2

    Good models for this task:
      - llama3.2       (3B, fast, good tool-calling)
      - llama3.1:8b    (8B, better reasoning)
      - mistral        (7B, excellent instruction following)
      - qwen2.5:7b     (strong multilingual + tool use)
    """

    def get_chat_model(self) -> BaseChatModel:
        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=0.3,
            num_ctx=4096,             # context window
        )

    def get_provider_name(self) -> str:
        return f"Ollama ({settings.ollama_model})"
