from llm.base import LLMProvider
from config import settings


def build_llm_provider() -> LLMProvider:
    """
    Single factory function — reads LLM_PROVIDER from env.
    The rest of the app never imports a specific provider directly.
    """
    provider = settings.llm_provider.lower()

    if provider == "gemini":
        from llm.gemini import GeminiProvider
        return GeminiProvider()

    elif provider == "ollama":
        from llm.ollama_provider import OllamaProvider
        return OllamaProvider()

    elif provider == "llamacpp":
        from llm.llamacpp_provider import LlamaCppProvider
        return LlamaCppProvider()

    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER: '{provider}'. "
            f"Choose: gemini | ollama | llamacpp"
        )


# Singleton — built once, shared across the app
llm_provider: LLMProvider = build_llm_provider()
