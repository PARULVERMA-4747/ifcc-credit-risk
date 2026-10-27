"""
Scoring + decisioning engine (Steps 13, 17, 32, 33, 34).

Uses ONLY artifacts/scorecard.json, so the same logic can run in Python,
the API, or the browser app. Flow for one application:

  validate -> derive features -> scorecard points -> score -> PD -> grade
  -> policy rules + fraud signals -> decision (APPROVE / REFER / DECLINE)
  -> reason codes -> expected loss -> decision trace
"""
import json, math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SC = json.loads((ROOT / "artifacts" / "scorecard.json").read_text())

REASON_TEXT = {
    "dti": "Debt-to-income ratio is high",
    "employment_type": "Employment type indicates less stable income",
    "credit_utilization": "Credit card / revolving utilisation is high",
    "annual_income": "Annual income is low relative to other applicants",
    "credit_history_years": "Length of credit history is short",
    "num_delinquencies_2y": "Recent delinquencies on credit file",
    "loan_to_income": "Requested loan is large relative to income",
    "employment_years": "Time in current employment is short",
    "num_inquiries_6m": "Several recent credit enquiries",
    "loan_term_months": "Requested loan term is long",
}

REQUIRED = {
    "employment_type": str, "employment_years": (int, float, type(None)),
    "home_ownership": str, "annual_income": (int, float),
    "credit_history_years": (int, float), "num_open_accounts": int,
    "credit_utilization": (int, float, type(None)), "num_inquiries_6m": int,
    "num_delinquencies_2y": int, "existing_monthly_debt": (int, float),
    "loan_purpose": str, "loan_amount": (int, float), "loan_term_months": int,
}


def derive(app: dict) -> dict:
    """Financial analysis: compute DTI (incl. new EMI at 14% APR) and loan-to-income."""
    a = dict(app)
    r = 0.14 / 12
    emi = a["loan_amount"] * r / (1 - (1 + r) ** -a["loan_term_months"])
    monthly_inc = max(a["annual_income"], 1) / 12
    a["new_emi"] = round(emi, 2)
    a["dti"] = round(min((a["existing_monthly_debt"] + emi) / monthly_inc, 2), 3)
    a["loan_to_income"] = round(a["loan_amount"] / max(a["annual_income"], 1), 3)
    return a


def _points(feat: str, value):
    spec = SC["features"][feat]
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return spec.get("missing_points", spec["neutral_points"]), "__MISSING__"
    if spec["type"] == "categorical":
        lab = str(value)
        return spec["points"].get(lab, spec["neutral_points"]), lab
    for b in spec["bins"]:
        lo = -math.inf if b["lower"] is None else b["lower"]
        hi = math.inf if b["upper"] is None else b["upper"]
        if lo <= value < hi:
            return b["points"], b["label"]
    return spec["neutral_points"], "out_of_range"


def grade_of(score: float) -> str:
    for g, lb in SC["grades"]:
        if score >= lb:
            return g
    return SC["grades"][-1][0]


def score_application(app: dict) -> dict:
    a = derive(app)
    contribs, total = [], 0.0
    for f, spec in SC["features"].items():
        pts, lab = _points(f, a.get(f))
        best = max(spec["points"].values())
        contribs.append({"feature": f, "value": a.get(f), "bin": lab,
                         "points": round(pts, 2), "max_points": round(best, 2),
                         "points_lost": round(best - pts, 2)})
        total += pts
    score = max(SC["score_min"], min(SC["score_max"], total))
    log_odds_good = (score - SC["offset"]) / SC["factor"]
    pd_ = 1 / (1 + math.exp(log_odds_good))
    grade = grade_of(score)

    # ---- policy rules + fraud / anomaly signals (governed, deterministic)
    P = SC["policy"]
    rules = []
    if a["annual_income"] < P["min_annual_income"]:
        rules.append(("DECLINE", "POL-01", "Annual income below policy minimum"))
    if a["dti"] > P["max_dti_decline"]:
        rules.append(("DECLINE", "POL-02", "Debt-to-income above policy maximum"))
    elif a["dti"] > P["max_dti_refer"]:
        rules.append(("REFER", "POL-03", "Debt-to-income in referral zone"))
    if a["num_delinquencies_2y"] >= P["max_delinquencies_refer"]:
        rules.append(("REFER", "POL-04", "Multiple recent delinquencies"))
    if a["loan_amount"] > P["max_loan_amount_auto"]:
        rules.append(("REFER", "POL-05", "Loan amount above auto-approval limit"))
    if a["num_inquiries_6m"] >= P["fraud_inquiries"] and a["loan_to_income"] > P["fraud_lti"]:
        rules.append(("REFER", "FRD-01", "Fraud signal: many enquiries with high loan-to-income"))

    # ---- decision
    if score >= SC["approve_cutoff"]:
        model_decision = "APPROVE"
    elif score >= SC["refer_cutoff"]:
        model_decision = "REFER"
    else:
        model_decision = "DECLINE"
    actions = [r[0] for r in rules] + [model_decision]
    decision = "DECLINE" if "DECLINE" in actions else "REFER" if "REFER" in actions else "APPROVE"

    # ---- adverse-action reason codes (biggest points lost)
    lost = sorted([c for c in contribs if c["points_lost"] > 0.5], key=lambda c: -c["points_lost"])
    reasons = [{"code": f"RC-{c['feature'].upper()}", "text": REASON_TEXT.get(c["feature"], c["feature"]),
                "points_lost": c["points_lost"]} for c in lost[:4]]

    ead = a["loan_amount"]
    return {
        "model_version": SC["model_version"],
        "score": round(score, 1), "pd_12m": round(pd_, 4), "grade": grade,
        "decision": decision, "model_decision": model_decision,
        "policy_rules_fired": [{"action": x, "rule_id": i, "text": t} for x, i, t in rules],
        "reason_codes": reasons if decision != "APPROVE" else [],
        "expected_loss": {"pd": round(pd_, 4), "lgd": SC["lgd"], "ead": ead,
                          "el": round(pd_ * SC["lgd"] * ead, 2)},
        "derived": {"dti": a["dti"], "loan_to_income": a["loan_to_income"], "new_emi": a["new_emi"]},
        "trace": contribs,
    }


def validate(app: dict) -> list:
    errs = []
    for k, t in REQUIRED.items():
        if k not in app:
            errs.append(f"missing field: {k}")
        elif not isinstance(app[k], t) or isinstance(app[k], bool):
            errs.append(f"bad type for {k}")
    if not errs:
        if app["annual_income"] < 0 or app["loan_amount"] <= 0:
            errs.append("income must be >= 0 and loan_amount > 0")
        if app["loan_term_months"] not in (12, 24, 36, 48, 60):
            errs.append("loan_term_months must be one of 12,24,36,48,60")
        cu = app.get("credit_utilization")
        if cu is not None and not 0 <= cu <= 1:
            errs.append("credit_utilization must be between 0 and 1")
    return errs


if __name__ == "__main__":
    demo = {"employment_type": "Salaried", "employment_years": 6, "home_ownership": "Mortgage",
            "annual_income": 72000, "credit_history_years": 11, "num_open_accounts": 4,
            "credit_utilization": 0.22, "num_inquiries_6m": 1, "num_delinquencies_2y": 0,
            "existing_monthly_debt": 600, "loan_purpose": "Home Improvement",
            "loan_amount": 12000, "loan_term_months": 36}
    r = score_application(demo)
    print(json.dumps({k: v for k, v in r.items() if k != "trace"}, indent=2))
