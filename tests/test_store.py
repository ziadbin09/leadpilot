import pytest

from app.scoring import LeadFields
from app.store import Store


def test_upsert_same_email_updates_not_duplicates():
    s = Store(":memory:")
    a = s.upsert_lead(LeadFields(email="a@x.com", need="chatbot"))
    b = s.upsert_lead(LeadFields(email="a@x.com", budget_usd=6000))
    assert a == b
    rows = s.list_leads()
    assert len(rows) == 1
    assert rows[0]["budget_usd"] == 6000
    assert rows[0]["need"] == "chatbot"


def test_score_recomputed_on_merge():
    s = Store(":memory:")
    s.upsert_lead(LeadFields(email="a@x.com", need="chatbot"))
    assert s.list_leads()[0]["tier"] == "cold"
    s.upsert_lead(LeadFields(email="a@x.com", budget_usd=9000, timeline_days=14,
                             is_decision_maker=True))
    row = s.list_leads()[0]
    assert row["score"] == 100
    assert row["tier"] == "hot"


def test_upsert_without_email_creates_new_row():
    s = Store(":memory:")
    s.upsert_lead(LeadFields(need="a"))
    s.upsert_lead(LeadFields(need="b"))
    assert len(s.list_leads()) == 2


def test_booking_shows_in_list():
    s = Store(":memory:")
    lid = s.upsert_lead(LeadFields(email="a@x.com"))
    assert s.list_leads()[0]["booked_slot"] is None
    s.add_booking(lid, "2026-12-01T10:00:00+00:00")
    assert s.list_leads()[0]["booked_slot"] == "2026-12-01T10:00:00+00:00"


def test_email_matching_is_case_insensitive():
    s = Store(":memory:")
    s.upsert_lead(LeadFields(email="Sara@X.com", need="x"))
    s.upsert_lead(LeadFields(email=" sara@x.com ", budget_usd=100))
    rows = s.list_leads()
    assert len(rows) == 1
    assert rows[0]["email"] == "sara@x.com"


def test_add_booking_unknown_lead_raises():
    s = Store(":memory:")
    with pytest.raises(KeyError):
        s.add_booking(999, "2026-12-01T10:00:00+00:00")


def test_decision_maker_roundtrips_bool_and_none_and_order():
    s = Store(":memory:")
    s.upsert_lead(LeadFields(is_decision_maker=False))
    s.upsert_lead(LeadFields(is_decision_maker=True))
    s.upsert_lead(LeadFields())
    rows = s.list_leads()
    assert [r["is_decision_maker"] for r in rows] == [None, True, False]
    assert rows[0]["id"] > rows[1]["id"] > rows[2]["id"]
    assert rows[0]["created_at"]
