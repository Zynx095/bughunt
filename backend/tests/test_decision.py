from app.core.contracts import ExecutionContext


def test_rules_dsl(run):
    rules = [
        {"id": "big", "when": {"field": "amount", "op": "gt", "value": 100}, "severity": "medium", "outcome": "review"},
        {"id": "combo", "severity": "high", "outcome": "block", "when": {"all": [
            {"field": "country", "op": "in", "value": ["XX", "YY"]},
            {"not": {"field": "verified", "op": "eq", "value": True}},
            {"any": [{"field": "note", "op": "regex", "value": "^urgent"}, {"field": "amount", "op": "between", "value": [1000, 5000]}]},
        ]}},
        {"id": "nested", "when": {"field": "meta.score", "op": "gte", "value": 0.9}, "severity": "low", "outcome": "tag"},
    ]
    facts = [
        {"amount": 50, "country": "FR", "verified": True},
        {"amount": 2000, "country": "XX", "verified": False, "meta": {"score": 0.95}},
        {"amount": 150, "note": "urgent pay", "country": "YY"},
    ]
    r = run("decision", "evaluate_rules", {"rules": rules, "facts": facts}).result["results"]
    assert r[0]["outcome"] == "pass" and r[0]["matched"] == []
    assert r[1]["outcome"] == "block" and {m["id"] for m in r[1]["matched"]} == {"big", "combo", "nested"}
    assert r[2]["outcome"] == "block"


def test_rules_reject_malformed_condition(run):
    r = run("decision", "evaluate_rules", {"rules": [{"id": "x", "when": {"field": "a"}}], "facts": {}})
    assert not r.success and r.error.code == "INVALID_INPUT"


def test_risk_score_contributions(run):
    r = run("decision", "risk_score", {"factors": [
        {"name": "a", "value": 1, "weight": 3}, {"name": "b", "value": 0, "weight": 1},
        {"name": "c", "value": 20, "min": 10, "max": 30, "weight": 1, "invert": True}]}).result
    assert r["score"] == 70.0 and r["band"] == "high"
    assert abs(sum(c["points"] for c in r["contributions"]) - r["score"]) < 0.05
    assert r["contributions"][0]["factor"] == "a"


def test_aggregate_confidence_reflects_agreement(run):
    agree = run("decision", "aggregate", {"signals": [{"source": "a", "score": 0.8}, {"source": "b", "score": 0.82}]})
    disagree = run("decision", "aggregate", {"signals": [{"source": "a", "score": 0.05}, {"source": "b", "score": 0.95}]})
    assert agree.confidence > disagree.confidence
    partial = run("decision", "aggregate", {"signals": [{"source": "a", "score": 0.8}, {"source": "b", "score": 0.8}],
                                            "expected_sources": 4})
    assert partial.result["coverage"] == 0.5


def test_approval_workflow(services):
    reg = services.registry
    alice = ExecutionContext(actor="alice", role="analyst")
    bob = ExecutionContext(actor="bob", role="reviewer")
    req = reg.execute("decision", "request_approval", {"title": "Hold T1", "action": "hold", "risk_score": 80}, alice)
    aid = req.result["id"]
    assert req.result["status"] == "pending"
    # analyst lacks approval:decide
    assert reg.execute("decision", "decide_approval", {"approval_id": aid, "decision": "approve"}, alice).error.code == "FORBIDDEN"
    # reviewer cannot approve their own request
    own = reg.execute("decision", "request_approval", {"title": "Own", "action": "x"}, bob).result["id"]
    assert reg.execute("decision", "decide_approval", {"approval_id": own, "decision": "approve"}, bob).error.code == "SELF_APPROVAL"
    # AI actors are blocked by policy even with an admin role
    ai = ExecutionContext(actor="agent", role="admin", actor_type="ai")
    assert reg.execute("decision", "decide_approval", {"approval_id": aid, "decision": "approve"}, ai).error.code == "FORBIDDEN"
    ok = reg.execute("decision", "decide_approval", {"approval_id": aid, "decision": "reject", "note": "false positive"}, bob)
    assert ok.success and ok.result["status"] == "rejected" and ok.result["reviewer"] == "bob"
    again = reg.execute("decision", "decide_approval", {"approval_id": aid, "decision": "approve"}, bob)
    assert again.error.code == "ALREADY_DECIDED"
