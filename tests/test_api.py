from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.calendars import FakeCalendar
from app.config import Settings
from app.main import create_app
from app.scoring import LeadFields
from app.store import Store


class StubLLM:
    def __init__(self, text="Hi, what are you building?"):
        self.text = text
        self.calls = []

    def create(self, messages, tools):
        self.calls.append([dict(m) for m in messages])
        return SimpleNamespace(content=self.text, tool_calls=None)


def settings(key="test-key"):
    return Settings(base_url="http://stub", api_key=key, model="m", google_credentials_file=None)


def make(llm=None, key="test-key"):
    store = Store(":memory:")
    cal = FakeCalendar(now=lambda: datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc))
    app = create_app(settings=settings(key), llm=llm, store=store, cal=cal)
    return TestClient(app), store


def post(client, message="hello", sid="s1"):
    return client.post("/chat", json={"session_id": sid, "message": message})


def test_chat_returns_reply():
    llm = StubLLM("Hello there")
    client, _ = make(llm)
    r = post(client)
    assert r.status_code == 200
    assert r.json() == {"reply": "Hello there"}
    assert llm.calls[0][-1] == {"role": "user", "content": "hello"}


def test_history_accumulates_within_session():
    llm = StubLLM()
    client, _ = make(llm)
    post(client, "one")
    post(client, "two")
    contents = [m.get("content") for m in llm.calls[1]]
    assert "one" in contents and "two" in contents


@pytest.mark.parametrize("message", ["", "   ", "x" * 1001])
def test_bad_message_422_without_llm_call(message):
    llm = StubLLM()
    client, _ = make(llm)
    assert post(client, message).status_code == 422
    assert llm.calls == []


def test_exactly_1000_chars_ok():
    client, _ = make(StubLLM())
    assert post(client, "x" * 1000).status_code == 200


def test_bad_session_id_422():
    client, _ = make(StubLLM())
    assert post(client, sid="").status_code == 422
    assert post(client, sid="s" * 101).status_code == 422


def test_missing_key_returns_503(caplog):
    client, _ = make(llm=None, key=None)
    r = post(client)
    assert r.status_code == 503
    assert ".env" in r.json()["detail"]
    assert "Traceback" not in r.text
    assert all(rec.exc_info is None for rec in caplog.records)


def test_session_message_cap():
    llm = StubLLM()
    client, _ = make(llm)
    for _ in range(20):
        assert post(client).status_code == 200
    r = post(client)
    assert r.status_code == 200
    assert "email" in r.json()["reply"]
    assert len(llm.calls) == 20


def test_sessions_are_isolated():
    llm = StubLLM()
    client, _ = make(llm)
    post(client, "from A", sid="a")
    post(client, "from B", sid="b")
    contents = [m.get("content") for m in llm.calls[1]]
    assert "from B" in contents and "from A" not in contents


def test_leads_endpoint_lists_saved_lead():
    client, store = make(StubLLM())
    assert client.get("/leads").json() == []
    store.upsert_lead(LeadFields(name="Sara", email="sara@example.com", need="store", budget_usd=6000))
    leads = client.get("/leads").json()
    assert len(leads) == 1 and leads[0]["email"] == "sara@example.com"


def test_index_served():
    client, _ = make(StubLLM())
    r = client.get("/")
    assert r.status_code == 200 and "LeadPilot" in r.text
    assert client.get("/static/app.js").status_code == 200


def test_capped_session_captures_email_without_llm():
    llm = StubLLM()
    client, _ = make(llm)
    for _ in range(20):
        post(client)
    r = post(client, "sure, it's sara@example.com.")
    assert r.status_code == 200
    assert "sara@example.com" in r.json()["reply"] and "reach out" in r.json()["reply"]
    assert len(llm.calls) == 20
    leads = client.get("/leads").json()
    assert [l["email"] for l in leads] == ["sara@example.com"]


def test_capped_session_without_email_keeps_cap_reply():
    client, _ = make(StubLLM())
    for _ in range(20):
        post(client)
    r = post(client, "no thanks")
    assert "please leave your email" in r.json()["reply"]
    assert client.get("/leads").json() == []


class SaveNeedOnceLLM(StubLLM):
    """First call saves a need via the tool, then plain replies."""

    def create(self, messages, tools):
        if not self.calls:
            self.calls.append([dict(m) for m in messages])
            call = SimpleNamespace(id="c1", type="function", function=SimpleNamespace(
                name="save_lead_fields", arguments='{"need": "shop"}'))
            return SimpleNamespace(content=None, tool_calls=[call])
        return super().create(messages, tools)


def test_capped_email_updates_the_sessions_anonymous_lead():
    client, _ = make(SaveNeedOnceLLM())
    for _ in range(20):
        post(client)
    post(client, "bo@x.io")
    leads = client.get("/leads").json()
    assert len(leads) == 1
    assert leads[0]["email"] == "bo@x.io" and leads[0]["need"] == "shop"
