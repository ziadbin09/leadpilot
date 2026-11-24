from dataclasses import dataclass


@dataclass
class LeadFields:
    need: str | None = None
    budget_usd: int | None = None
    timeline_days: int | None = None
    is_decision_maker: bool | None = None
    email: str | None = None
    name: str | None = None


def score_lead(f: LeadFields) -> tuple[int, str]:
    score = 0
    if f.budget_usd is not None:
        score += 40 if f.budget_usd >= 5000 else 25 if f.budget_usd >= 1000 else 5
    if f.timeline_days is not None:
        score += 30 if f.timeline_days <= 30 else 15 if f.timeline_days <= 90 else 5
    if f.is_decision_maker is not None:
        score += 20 if f.is_decision_maker else 5
    if f.need and f.need.strip():
        score += 10
    tier = "hot" if score >= 70 else "warm" if score >= 40 else "cold"
    return score, tier
