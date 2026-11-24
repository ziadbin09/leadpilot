import openai

from app.config import Settings


class OpenAICompatLLM:
    """Thin wrapper over an OpenAI-compatible chat endpoint (Gemini by default)."""

    def __init__(self, settings: Settings):
        if settings.api_key is None:
            raise RuntimeError("LLM_API_KEY is not set; copy .env.example to .env")
        self._model = settings.model
        # one retry at most: a failing provider must not keep a visitor waiting for minutes
        self._client = openai.OpenAI(
            base_url=settings.base_url, api_key=settings.api_key, max_retries=1
        )

    def create(self, messages: list[dict], tools: list[dict]):
        resp = self._client.chat.completions.create(
            model=self._model, messages=messages, tools=tools, timeout=20
        )
        return resp.choices[0].message
