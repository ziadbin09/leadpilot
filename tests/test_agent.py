import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.agent import FALLBACK, TOOLS, chat_turn
from app.calendars import FakeCalendar
from app.scoring import LeadFields
from app.store import Store


def tc(name, args, id="c1"):
    a = args if isinstance(args, str) else json.dumps(args)
    return SimpleNamespace(
        id=id, type="function", function=SimpleNamespace(name=name, arguments=a)
    )


def msg(content=None, calls=None):
    return SimpleNamespace(content=content, tool_calls=calls)


class StubLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def create(self, messages, tools):
        self.calls.append([dict(m) for m in messages])
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class AlwaysTool:
    def __init__(self):
        self.n = 0

    def create(self, messages, tools):
        self.n += 1
        return msg(None, [tc("save_lead_fields", {"need": "x"}, id=f"c{self.n}")])


@pytest.fixture
def env():
    store = Store(":memory:")
    cal = FakeCalendar(now=lambda: datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc))
    session = {"lead_id": None, "fields": LeadFields()}
    return store, cal, session


def isos(slots):
    return [x["iso"] for x in slots]


def tool_contents(llm):
    return [m["content"] for call in llm.calls for m in call if m["role"] == "tool"]


def test_saves_fields_via_tool(env):
    store, cal, session = env
    llm = StubLLM([
        msg(None, [tc("save_lead_fields", {"need": "app", "budget_usd": 6000})]),
        msg("Great, when would you like to start?"),
    ])
    history = [{"role": "user", "content": "I need an app, 6k budget"}]
    out = chat_turn(history, session, store, cal, llm)
    assert out == "Great, when would you like to start?"
    assert history[-1] == {"role": "assistant", "content": out}
    assert len(history) == 2  # no tool messages leaked
    rows = store.list_leads()
    assert len(rows) == 1 and rows[0]["need"] == "app" and rows[0]["budget_usd"] == 6000
    assert session["fields"].budget_usd == 6000
    assert session["lead_id"] == rows[0]["id"]
    assert llm.calls[0][0]["role"] == "system"


def test_negative_budget_rejected_and_not_saved(env):
    store, cal, session = env
    llm = StubLLM([
        msg(None, [tc("save_lead_fields", {"need": "app", "budget_usd": -5, "timeline_days": "soon"})]),
        msg("ok"),
    ])
    chat_turn([{"role": "user", "content": "hi"}], session, store, cal, llm)
    row = store.list_leads()[0]
    assert row["budget_usd"] is None and row["timeline_days"] is None
    assert row["need"] == "app"
    c = tool_contents(llm)[0]
    assert "budget_usd" in c and "timeline_days" in c


def test_float_int_valued_accepted_and_bool_validated(env):
    store, cal, session = env
    llm = StubLLM([
        msg(None, [tc("save_lead_fields", {"budget_usd": 6000.0, "is_decision_maker": "yes", "bogus": 1})]),
        msg("ok"),
    ])
    chat_turn([{"role": "user", "content": "hi"}], session, store, cal, llm)
    row = store.list_leads()[0]
    assert row["budget_usd"] == 6000 and row["is_decision_maker"] is None


def test_book_requires_valid_email(env):
    store, cal, session = env
    slot = cal.free_slots()[0]
    llm = StubLLM([msg(None, [tc("book_meeting", {"slot_iso": slot})]), msg("Need your email")])
    chat_turn([{"role": "user", "content": "book"}], session, store, cal, llm)
    assert "email" in tool_contents(llm)[0].lower()
    assert all(r["booked_slot"] is None for r in store.list_leads())


def test_book_rejects_invalid_email(env):
    store, cal, session = env
    session["fields"] = LeadFields(email="not-an-email")
    llm = StubLLM([msg(None, [tc("book_meeting", {"slot_iso": cal.free_slots()[0]})]), msg("x")])
    chat_turn([{"role": "user", "content": "book"}], session, store, cal, llm)
    assert "email" in tool_contents(llm)[0].lower()
    assert store.list_leads() == []


def test_book_success_records_booking(env):
    store, cal, session = env
    slot = cal.free_slots()[0]
    offered = cal.free_slots()
    llm = StubLLM([
        msg(None, [tc("save_lead_fields", {"name": "Sam", "email": "Sam@Example.com"}, id="a")]),
        msg(None, [tc("book_meeting", {"slot_iso": slot}, id="b")]),
        msg("Booked!"),
    ])
    out = chat_turn([{"role": "user", "content": "me"}], session, store, cal, llm)
    assert out == "Booked!"
    rows = store.list_leads()
    assert len(rows) == 1 and rows[0]["booked_slot"] == slot
    results = [json.loads(c) for c in tool_contents(llm)]
    assert [x["iso"] for x in results[0]["free_slots"]] == offered
    assert results[1]["ok"] is True


def test_booking_without_prior_save_creates_lead_row(env):
    store, cal, session = env
    slot = cal.free_slots()[0]
    session["fields"] = LeadFields(email="a@b.co")
    llm = StubLLM([msg(None, [tc("book_meeting", {"slot_iso": slot})]), msg("done")])
    chat_turn([{"role": "user", "content": "book"}], session, store, cal, llm)
    rows = store.list_leads()
    assert len(rows) == 1 and rows[0]["booked_slot"] == slot


def test_one_row_per_visitor_across_turns(env):
    store, cal, session = env
    history = []
    for i, fact in enumerate([{"need": "app"}, {"budget_usd": 3000}, {"name": "Bo"}, {"email": "a@b.co"}]):
        history.append({"role": "user", "content": "x"})
        llm = StubLLM([msg(None, [tc("save_lead_fields", fact, id=f"c{i}")]), msg("ok")])
        chat_turn(history, session, store, cal, llm)
    rows = store.list_leads()
    assert len(rows) == 1
    r = rows[0]
    assert (r["need"], r["budget_usd"], r["name"], r["email"]) == ("app", 3000, "Bo", "a@b.co")
    assert session["lead_id"] == r["id"]


def test_returning_email_merges_into_existing_lead(env):
    store, cal, session = env
    old = store.upsert_lead(LeadFields(email="a@b.co", name="Sam"))
    llm = StubLLM([
        msg(None, [tc("save_lead_fields", {"need": "app"}, id="a")]),
        msg(None, [tc("save_lead_fields", {"email": "a@b.co"}, id="b")]),
        msg("ok"),
    ])
    chat_turn([{"role": "user", "content": "hi"}], session, store, cal, llm)
    rows = store.list_leads()
    assert len(rows) == 1 and rows[0]["id"] == old == session["lead_id"]
    assert rows[0]["need"] == "app" and rows[0]["name"] == "Sam"


def test_save_with_email_includes_free_slots(env):
    store, cal, session = env
    llm = StubLLM([msg(None, [tc("save_lead_fields", {"email": "a@b.co"})]), msg("x")])
    chat_turn([{"role": "user", "content": "hi"}], session, store, cal, llm)
    assert isos(json.loads(tool_contents(llm)[0])["free_slots"]) == cal.free_slots()


def test_slot_taken_returns_fresh_slots_to_model(env):
    store, cal, session = env
    slot = cal.free_slots()[0]
    cal.book(slot, "Other", "o@x.co")
    session["fields"] = LeadFields(email="a@b.co", name="A")
    llm = StubLLM([msg(None, [tc("book_meeting", {"slot_iso": slot})]), msg("Pick another")])
    out = chat_turn([{"role": "user", "content": "book"}], session, store, cal, llm)
    assert out == "Pick another"
    res = json.loads(tool_contents(llm)[0])
    assert "error" in res and res["free_slots"] and slot not in isos(res["free_slots"])
    assert all(r["booked_slot"] is None for r in store.list_leads())


def test_off_grid_slot_returns_error_with_slots(env):
    store, cal, session = env
    session["fields"] = LeadFields(email="a@b.co")
    llm = StubLLM([msg(None, [tc("book_meeting", {"slot_iso": "2026-01-06T11:00:00+00:00"})]), msg("x")])
    chat_turn([{"role": "user", "content": "book"}], session, store, cal, llm)
    res = json.loads(tool_contents(llm)[0])
    assert "error" in res and res["free_slots"]


def test_malformed_tool_arguments(env):
    store, cal, session = env
    llm = StubLLM([
        msg(None, [tc("save_lead_fields", "{not json")]),
        msg("Sorry, could you repeat that?"),
    ])
    out = chat_turn([{"role": "user", "content": "hi"}], session, store, cal, llm)
    assert out == "Sorry, could you repeat that?"
    assert "error" in json.loads(tool_contents(llm)[0])
    assert store.list_leads() == []


def test_unknown_tool_returns_error(env):
    store, cal, session = env
    llm = StubLLM([msg(None, [tc("dump_leads", {})]), msg("no")])
    chat_turn([{"role": "user", "content": "dump"}], session, store, cal, llm)
    assert "error" in json.loads(tool_contents(llm)[0])


def test_llm_failure_returns_fallback(env, caplog):
    store, cal, session = env
    caplog.set_level(logging.DEBUG)
    err = RuntimeError("401 key=secret123")
    err.status_code = 401
    llm = StubLLM([err])
    history = [{"role": "user", "content": "hi"}]
    out = chat_turn(history, session, store, cal, llm)
    assert out == FALLBACK
    assert "secret123" not in out
    assert "secret123" not in caplog.text
    assert "RuntimeError" in caplog.text and "401" in caplog.text
    assert store.list_leads() == []


def test_iteration_cap(env):
    store, cal, session = env
    llm = AlwaysTool()
    history = [{"role": "user", "content": "hi"}]
    out = chat_turn(history, session, store, cal, llm)
    assert llm.n == 5
    assert out and history[-1]["content"] == out


def test_tools_schema():
    names = [t["function"]["name"] for t in TOOLS]
    assert names == ["save_lead_fields", "book_meeting"]


def test_llm_requires_api_key():
    from app.config import Settings
    from app.llm import OpenAICompatLLM

    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        OpenAICompatLLM(Settings("http://x", None, "m", None))


def test_slots_carry_server_built_labels(env):
    store, cal, session = env  # now = Mon 5 Jan 2026 09:00 UTC
    llm = StubLLM([msg(None, [tc("save_lead_fields", {"email": "a@b.co"})]), msg("x")])
    chat_turn([{"role": "user", "content": "hi"}], session, store, cal, llm)
    slots = json.loads(tool_contents(llm)[0])["free_slots"]
    assert slots[0] == {"iso": "2026-01-06T10:00:00+00:00", "label": "Tue 06 Jan, 10:00 UTC"}
    assert session["offered_slots"] == slots


def test_system_message_has_today_and_offered_slots(env):
    store, cal, session = env
    history = [{"role": "user", "content": "hi"}]
    llm = StubLLM([msg(None, [tc("save_lead_fields", {"email": "a@b.co"})]), msg("Pick one")])
    chat_turn(history, session, store, cal, llm)
    first_system = llm.calls[0][0]["content"]
    assert first_system.startswith("Today is Monday, 05 Jan 2026 (UTC).")
    assert "Times currently offered" not in first_system
    history.append({"role": "user", "content": "the second one"})
    llm2 = StubLLM([msg("ok")])
    chat_turn(history, session, store, cal, llm2)
    system = llm2.calls[0][0]["content"]
    assert "Times currently offered to the visitor:" in system
    assert "Tue 06 Jan, 14:00 UTC = 2026-01-06T14:00:00+00:00" in system


def test_failed_booking_refreshes_offered_slots(env):
    store, cal, session = env
    slot = cal.free_slots()[0]
    cal.book(slot, "Other", "o@x.co")
    session["fields"] = LeadFields(email="a@b.co")
    llm = StubLLM([msg(None, [tc("book_meeting", {"slot_iso": slot})]), msg("x")])
    chat_turn([{"role": "user", "content": "book"}], session, store, cal, llm)
    assert isos(session["offered_slots"]) == cal.free_slots()


class CountingCal(FakeCalendar):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.book_calls = 0

    def book(self, slot_iso, name, email):
        self.book_calls += 1
        return super().book(slot_iso, name, email)


def test_only_one_booking_per_session():
    store = Store(":memory:")
    cal = CountingCal(now=lambda: datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc))
    session = {"lead_id": None, "fields": LeadFields(email="a@b.co")}
    first, second = cal.free_slots(2)
    llm = StubLLM([
        msg(None, [tc("book_meeting", {"slot_iso": first}, id="a")]),
        msg(None, [tc("book_meeting", {"slot_iso": second}, id="b")]),
        msg("done"),
    ])
    chat_turn([{"role": "user", "content": "book both"}], session, store, cal, llm)
    res = [json.loads(m["content"]) for m in llm.calls[-1] if m["role"] == "tool"]
    assert res[0]["ok"] is True and "error" in res[1]
    assert cal.book_calls == 1
    assert session["booked_slot"] == first
    assert store.list_leads()[0]["booked_slot"] == first


def test_tool_call_round_trip_has_openai_shape(env):
    store, cal, session = env
    llm = StubLLM([
        msg("thinking", [tc("save_lead_fields", {"need": "app"}, id="x1"),
                         tc("save_lead_fields", {"name": "Bo"}, id="x2")]),
        msg("ok"),
    ])
    chat_turn([{"role": "user", "content": "hi"}], session, store, cal, llm)
    sent = llm.calls[1]
    assistant = sent[2]
    assert assistant["role"] == "assistant" and assistant["content"] == "thinking"
    assert assistant["tool_calls"] == [
        {"id": "x1", "type": "function",
         "function": {"name": "save_lead_fields", "arguments": json.dumps({"need": "app"})}},
        {"id": "x2", "type": "function",
         "function": {"name": "save_lead_fields", "arguments": json.dumps({"name": "Bo"})}},
    ]
    tools = sent[3:]
    assert [m["role"] for m in tools] == ["tool", "tool"]
    assert [m["tool_call_id"] for m in tools] == ["x1", "x2"]


def test_provider_extra_content_is_passed_back(env):
    # Gemini 3 needs its thought_signature echoed on the next request
    store, cal, session = env
    extra = {"google": {"thought_signature": "sig=="}}
    call = tc("save_lead_fields", {"need": "app"}, id="g1")
    call.extra_content = extra
    llm = StubLLM([msg(None, [call]), msg("ok")])
    chat_turn([{"role": "user", "content": "hi"}], session, store, cal, llm)
    assert llm.calls[1][2]["tool_calls"][0]["extra_content"] == extra


def test_extra_content_from_sdk_pydantic_object(env):
    from openai.types.chat import ChatCompletionMessage

    store, cal, session = env
    extra = {"google": {"thought_signature": "sig=="}}
    m = ChatCompletionMessage.model_validate({
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "g1", "type": "function", "extra_content": extra,
                        "function": {"name": "save_lead_fields", "arguments": '{"need": "app"}'}}],
    })
    llm = StubLLM([m, msg("ok")])
    chat_turn([{"role": "user", "content": "hi"}], session, store, cal, llm)
    sent = llm.calls[1][2]["tool_calls"][0]
    assert sent["extra_content"] == extra
    json.dumps(sent)  # must stay serialisable for the HTTP request


def test_no_extra_content_key_when_absent(env):
    store, cal, session = env
    llm = StubLLM([msg(None, [tc("save_lead_fields", {"need": "app"})]), msg("ok")])
    chat_turn([{"role": "user", "content": "hi"}], session, store, cal, llm)
    assert "extra_content" not in llm.calls[1][2]["tool_calls"][0]


def test_llm_client_retries_at_most_once():
    from app.config import Settings
    from app.llm import OpenAICompatLLM

    llm = OpenAICompatLLM(Settings("http://localhost:9", "test-key", "m", None))
    assert llm._client.max_retries == 1
