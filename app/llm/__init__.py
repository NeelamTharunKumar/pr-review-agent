import logging
from groq import Groq
from app.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self):
        self._groq = None
        self._gemini = None

    @property
    def groq(self) -> Groq:
        if self._groq is None:
            self._groq = Groq(api_key=settings.GROQ_API_KEY)
        return self._groq

    @property
    def gemini(self):
        if self._gemini is None:
            from google import genai
            self._gemini = genai.Client(api_key=settings.GEMINI_API_KEY)
        return self._gemini

    def complete(
        self,
        system: str,
        user: str,
        model: str = "llama-3.3-70b-versatile",
        max_tokens: int = 4096,
        temperature: float = 0.1,
    ) -> str:
        primary = settings.LLM_PRIMARY
        fallback = settings.LLM_FALLBACK

        if primary == "groq":
            try:
                logger.info(f"[LLM] Trying Groq ({model})")
                response = self.groq.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                result = response.choices[0].message.content
                logger.info(f"[LLM] Groq succeeded ({len(result)} chars)")
                return result
            except Exception as e:
                logger.warning(f"[LLM] Groq failed: {e}")

        if fallback == "gemini":
            try:
                logger.info("[LLM] Trying Gemini fallback")
                response = self.gemini.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=user,
                    config={
                        "system_instruction": system,
                        "max_output_tokens": max_tokens,
                        "temperature": temperature,
                    },
                )
                result = response.text
                logger.info(f"[LLM] Gemini succeeded ({len(result)} chars)")
                return result
            except Exception as e:
                logger.error(f"[LLM] Gemini also failed: {e}")
                raise

        raise RuntimeError(f"No LLM provider available (primary={primary}, fallback={fallback})")


llm_client = LLMClient()
