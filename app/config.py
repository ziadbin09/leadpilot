import os
from collections.abc import Mapping
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_MODEL = "gemini-2.5-flash"


@dataclass(frozen=True, repr=False)
class Settings:
    base_url: str
    api_key: str | None
    model: str
    google_credentials_file: str | None

    def __repr__(self) -> str:
        key = "'***'" if self.api_key else "None"
        return (
            f"Settings(base_url={self.base_url!r}, api_key={key}, "
            f"model={self.model!r}, "
            f"google_credentials_file={self.google_credentials_file!r})"
        )


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    if env is os.environ:
        load_dotenv()
    return Settings(
        base_url=env.get("LLM_BASE_URL") or DEFAULT_BASE_URL,
        api_key=env.get("LLM_API_KEY") or None,
        model=env.get("LLM_MODEL") or DEFAULT_MODEL,
        google_credentials_file=env.get("GOOGLE_CREDENTIALS_FILE") or None,
    )
