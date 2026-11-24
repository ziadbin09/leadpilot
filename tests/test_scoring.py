from app.scoring import LeadFields, score_lead


def test_hot_lead():
    f = LeadFields(need="website", budget_usd=5000, timeline_days=30, is_decision_maker=True)
    assert score_lead(f) == (100, "hot")


def test_cold_lead():
    f = LeadFields(need=None, budget_usd=500, timeline_days=200, is_decision_maker=False)
    assert score_lead(f) == (15, "cold")


def test_unknowns_score_zero():
    assert score_lead(LeadFields()) == (0, "cold")


def test_boundaries():
    assert score_lead(LeadFields(budget_usd=1000))[0] == 25
    assert score_lead(LeadFields(budget_usd=999))[0] == 5
    assert score_lead(LeadFields(timeline_days=90))[0] == 15
    assert score_lead(LeadFields(timeline_days=91))[0] == 5


def test_tier_edges():
    # 25 (budget 1000) + 15 (timeline 90) = 40
    assert score_lead(LeadFields(budget_usd=1000, timeline_days=90)) == (40, "warm")
    # 40 (budget 5000) + 30 (timeline 30) = 70
    assert score_lead(LeadFields(budget_usd=5000, timeline_days=30)) == (70, "hot")
    # 25 (budget 1000) + 5 (timeline 200) + 5 (not decision maker) = 35
    assert score_lead(LeadFields(budget_usd=1000, timeline_days=200, is_decision_maker=False)) == (35, "cold")
