"""
Steps 21-24: functional, integration, decision-validation and basic security tests.
Run:  pytest -q
"""
import json, os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["IFCC_AUDIT_FILE"] = str(Path(tempfile.mkdtemp()) / "audit.jsonl")
sys.path.insert(0, str(ROOT / "src"))

import pytest
from fastapi.testclient import TestClient
from score import score_application, validate
from api import app, AUDIT_FILE

client = TestClient(app)
OPS = {"X-API-Key": "ops-demo-key"}
UW = {"X-API-Key": "uw-demo-key"}

GOOD = {"employment_type": "Salaried", "employment_years": 8, "home_ownership": "Own",
        "annual_income": 95000, "credit_history_years": 15, "num_open_accounts": 4,
        "credit_utilization": 0.10, "num_inquiries_6m": 0, "num_delinquencies_2y": 0,
        "existing_monthly_debt": 300, "loan_purpose": "Home Improvement",
        "loan_amount": 8000, "loan_term_months": 24}
BAD = GOOD | {"employment_type": "Unemployed", "employment_years": 0, "annual_income": 14000,
              "credit_history_years": 1, "credit_utilization": 0.95, "num_inquiries_6m": 4,
              "num_delinquencies_2y": 2, "loan_purpose": "Travel", "loan_amount": 6000,
              "loan_term_months": 60, "home_ownership": "Rent"}


# ---------------- functional / decision validation (Step 21, 23)
def test_good_applicant_approved():
    r = score_application(GOOD)
    assert r["decision"] == "APPROVE" and r["grade"] in "AB" and r["reason_codes"] == []

def test_bad_applicant_declined_with_reasons():
    r = score_application(BAD)
    assert r["decision"] == "DECLINE"
    assert 1 <= len(r["reason_codes"]) <= 4

def test_score_monotonic_in_utilisation():
    s = [score_application(GOOD | {"credit_utilization": u})["score"] for u in (0.05, 0.4, 0.7, 0.95)]
    assert s == sorted(s, reverse=True)

def test_score_monotonic_in_delinquencies():
    s = [score_application(GOOD | {"num_delinquencies_2y": d})["score"] for d in (0, 1, 2)]
    assert s == sorted(s, reverse=True)

def test_policy_income_floor_declines():
    r = score_application(GOOD | {"annual_income": 10000, "loan_amount": 1000})
    assert r["decision"] == "DECLINE" and any(x["rule_id"] == "POL-01" for x in r["policy_rules_fired"])

def test_policy_large_loan_refers():
    r = score_application(GOOD | {"annual_income": 200000, "loan_amount": 45000})
    assert r["decision"] == "REFER" and any(x["rule_id"] == "POL-05" for x in r["policy_rules_fired"])

def test_missing_values_handled():
    r = score_application(GOOD | {"credit_utilization": None, "employment_years": None})
    assert 300 <= r["score"] <= 900

def test_expected_loss_formula():
    r = score_application(GOOD)
    el = r["expected_loss"]
    assert abs(el["el"] - el["pd"] * el["lgd"] * el["ead"]) < 1

def test_trace_sums_to_score():
    r = score_application(GOOD)
    assert abs(sum(c["points"] for c in r["trace"]) - r["score"]) < 0.5

def test_age_not_used():
    assert "age" not in json.loads((ROOT / "artifacts" / "scorecard.json").read_text())["features"]

def test_validation_rejects_bad_term():
    assert validate(GOOD | {"loan_term_months": 18})

def test_model_meets_acceptance_thresholds():
    m = json.loads((ROOT / "artifacts" / "metadata.json").read_text())["metrics"]
    t = m["champion_lr_woe"]["test"]
    assert t["gini"] >= 0.40 and t["ks"] >= 0.30 and m["psi_train_vs_test"] < 0.10


# ---------------- API integration + security (Step 22, 24)
def test_health():
    assert client.get("/health").json()["status"] == "ok"

def test_auth_required():
    assert client.post("/applications", json=GOOD).status_code == 401

def test_schema_validation_422():
    assert client.post("/applications", json=GOOD | {"loan_amount": -5}, headers=OPS).status_code == 422

def test_idempotent_create():
    h = OPS | {"Idempotency-Key": "abc-123"}
    a = client.post("/applications", json=GOOD, headers=h).json()
    b = client.post("/applications", json=GOOD, headers=h).json()
    assert a["application_ref"] == b["application_ref"]

def test_refer_then_human_review_and_audit():
    refer = GOOD | {"annual_income": 200000, "loan_amount": 45000}
    rec = client.post("/applications", json=refer, headers=OPS).json()
    assert rec["status"] == "PENDING_REVIEW"
    ref = rec["application_ref"]
    assert any(q["application_ref"] == ref for q in client.get("/review-queue", headers=OPS).json())
    # operations role cannot review
    assert client.post(f"/applications/{ref}/review", headers=OPS,
                       json={"final_decision": "APPROVE", "rationale": "verified income docs", "reviewer_id": "u1"}).status_code == 403
    r = client.post(f"/applications/{ref}/review", headers=UW,
                    json={"final_decision": "APPROVE", "rationale": "Verified salary slips and bank statements", "reviewer_id": "uw-07"})
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"
    assert client.get("/audit/verify", headers=OPS).json()["valid"] is True

def test_cannot_override_policy_decline():
    refer = GOOD | {"annual_income": 10000, "loan_amount": 45000}   # POL-01 decline + POL-05 refer
    rec = client.post("/applications", json=refer, headers=OPS).json()
    assert rec["status"] == "DECLINED"

def test_tamper_detected():
    client.post("/applications", json=GOOD, headers=OPS)
    lines = AUDIT_FILE.read_text().splitlines()
    rec = json.loads(lines[0]); rec["actor"] = "attacker"; lines[0] = json.dumps(rec)
    AUDIT_FILE.write_text("\n".join(lines) + "\n")
    assert client.get("/audit/verify", headers=OPS).json()["valid"] is False
