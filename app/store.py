import sqlite3
import threading
from datetime import datetime, timezone

from app.scoring import LeadFields, score_lead

_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    email TEXT,
    need TEXT,
    budget_usd INTEGER,
    timeline_days INTEGER,
    is_decision_maker INTEGER,
    score INTEGER NOT NULL DEFAULT 0,
    tier TEXT NOT NULL DEFAULT 'cold',
    booked_slot TEXT,
    created_at TEXT NOT NULL
)
"""


def _norm_email(email: str | None) -> str | None:
    email = (email or "").strip().lower()
    return email or None


class Store:
    def __init__(self, path: str = "leads.db"):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute(_SCHEMA)
            self._db.commit()

    def upsert_lead(self, f: LeadFields, lead_id: int | None = None) -> int:
        """Save a visitor's fields and return their row id.

        An email that matches an existing lead merges into that lead (and drops the
        session's own anonymous row, if any). Otherwise ``lead_id`` (the session's
        row) is updated in place. Only when neither applies is a new row inserted.
        """
        email = _norm_email(f.email)
        with self._lock:
            row = None
            if email:
                row = self._db.execute(
                    "SELECT * FROM leads WHERE email = ?", (email,)
                ).fetchone()
            own = None
            if lead_id is not None:
                own = self._db.execute(
                    "SELECT * FROM leads WHERE id = ?", (lead_id,)
                ).fetchone()
            if (row is not None and own is not None and own["id"] != row["id"]
                    and own["email"] is None):
                self._db.execute("DELETE FROM leads WHERE id = ?", (own["id"],))
            if row is None:
                row = own
            if row is None:
                merged = LeadFields(
                    need=f.need, budget_usd=f.budget_usd,
                    timeline_days=f.timeline_days,
                    is_decision_maker=f.is_decision_maker,
                    email=email, name=f.name,
                )
            else:
                merged = self._merge(row, f, email)
            score, tier = score_lead(merged)
            dm = None if merged.is_decision_maker is None else int(merged.is_decision_maker)
            if row is None:
                cur = self._db.execute(
                    "INSERT INTO leads (name, email, need, budget_usd, timeline_days,"
                    " is_decision_maker, score, tier, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (merged.name, merged.email, merged.need, merged.budget_usd,
                     merged.timeline_days, dm, score, tier,
                     datetime.now(timezone.utc).isoformat()),
                )
                out_id = cur.lastrowid
            else:
                out_id = row["id"]
                self._db.execute(
                    "UPDATE leads SET name = ?, email = ?, need = ?, budget_usd = ?,"
                    " timeline_days = ?, is_decision_maker = ?, score = ?, tier = ?"
                    " WHERE id = ?",
                    (merged.name, merged.email, merged.need, merged.budget_usd,
                     merged.timeline_days, dm, score, tier, out_id),
                )
            self._db.commit()
            return out_id

    @staticmethod
    def _merge(row: sqlite3.Row, f: LeadFields, email: str | None) -> LeadFields:
        def pick(new, old):
            return old if new is None else new

        old_dm = row["is_decision_maker"]
        return LeadFields(
            need=pick(f.need, row["need"]),
            budget_usd=pick(f.budget_usd, row["budget_usd"]),
            timeline_days=pick(f.timeline_days, row["timeline_days"]),
            is_decision_maker=pick(f.is_decision_maker,
                                   None if old_dm is None else bool(old_dm)),
            email=pick(email, row["email"]),
            name=pick(f.name, row["name"]),
        )

    def list_leads(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if d["is_decision_maker"] is not None:
                d["is_decision_maker"] = bool(d["is_decision_maker"])
            out.append(d)
        return out

    def add_booking(self, lead_id: int, slot_iso: str) -> None:
        with self._lock:
            cur = self._db.execute(
                "UPDATE leads SET booked_slot = ? WHERE id = ?", (slot_iso, lead_id)
            )
            self._db.commit()
            if cur.rowcount == 0:
                raise KeyError(f"lead {lead_id} not found")
