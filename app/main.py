import logging
import threading
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from app.agent import EMAIL_RE, chat_turn
from app.calendars import get_calendar
from app.config import Settings, load_settings
from app.llm import OpenAICompatLLM
from app.scoring import LeadFields
from app.store import Store

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"
DB_PATH = ROOT / "leads.db"  # repo root, not the current working directory
MAX_USER_MESSAGES = 20
MAX_SESSIONS = 1000
CAP_REPLY = (
    "Thanks for chatting! To keep going, please leave your email "
    "and our team will reach out."
)
NOT_CONFIGURED = "Server not configured: copy .env.example to .env and set LLM_API_KEY."


def _find_email(text: str) -> str | None:
    # reuse the agent's (anchored) email pattern on each whitespace-separated token
    for token in text.split():
        token = token.strip(".,;:!?()<>\"'")
        if EMAIL_RE.match(token):
            return token
    return None


class ChatIn(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1000)

    @field_validator("message")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be blank")
        return v


def create_app(settings: Settings | None = None, llm=None, store=None, cal=None) -> FastAPI:
    settings = settings or load_settings()
    store = store or Store(str(DB_PATH))
    cal = cal or get_calendar(settings)
    if llm is None and settings.api_key:
        llm = OpenAICompatLLM(settings)

    app = FastAPI(title="LeadPilot")
    # shortcut: in-memory sessions, lost on restart; oldest dropped past MAX_SESSIONS
    sessions: dict[str, dict] = {}
    lock = threading.Lock()

    @app.post("/chat")
    def chat(body: ChatIn) -> dict:
        if llm is None:
            log.warning("LLM_API_KEY is not set: copy .env.example to .env and add your key.")
            raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
        with lock:
            s = sessions.get(body.session_id)
            if s is None:
                if len(sessions) >= MAX_SESSIONS:
                    sessions.pop(next(iter(sessions)))
                s = sessions[body.session_id] = {
                    "history": [],
                    "session": {"lead_id": None, "fields": LeadFields()},
                    "user_messages": 0,
                }
            s["user_messages"] += 1
            if s["user_messages"] > MAX_USER_MESSAGES:
                email = _find_email(body.message)
                if not email:
                    return {"reply": CAP_REPLY}
                # past the cap: no LLM call, but still capture a willing lead's email
                sess = s["session"]
                sess["fields"] = replace(sess["fields"], email=email)
                sess["lead_id"] = store.upsert_lead(sess["fields"], sess["lead_id"])
                return {"reply": f"Thanks! Our team will reach out to you at {email}."}
            s["history"].append({"role": "user", "content": body.message})
        return {"reply": chat_turn(s["history"], s["session"], store, cal, llm)}

    @app.get("/leads")
    def leads() -> list[dict]:
        return store.list_leads()

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
