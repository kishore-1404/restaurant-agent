from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.language_models import BaseChatModel
from llm.base import LLMProvider
from config import settings


class GeminiProvider(LLMProvider):
    """
    Google Gemini via LangChain.
    Requires GEMINI_API_KEY in .env.
    Best model for tool-calling: gemini-1.5-flash (fast + free tier).
    """

    def get_chat_model(self) -> BaseChatModel:
        return ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key,
            temperature=0.3,          # lower = more predictable order-taking
            max_output_tokens=1024,
            convert_system_message_to_human=True,  # Gemini quirk
        )

    def get_provider_name(self) -> str:
        return f"Gemini ({settings.gemini_model})"
