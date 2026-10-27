"""
IFCC Bank Underwriting API (Steps 14, 17, 19, 30-34).

Run:   uvicorn src.api:app --reload      (from project root)
Docs:  http://127.0.0.1:8000/docs

Endpoints
  GET  /health                     liveness + model version
  POST /applications               intake -> validate -> score -> decide -> audit
  GET  /applications/{id}          fetch stored application + decision
  GET  /review-queue               REFER cases waiting for an underwriter
  POST /applications/{id}/review   human decision / override with rationale (RBAC by API key)
  GET  /audit/verify               re-check the tamper-evident hash chain
"""
import hashlib, json, logging, os, sys, time, uuid, threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Literal

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score import score_application, validate, SC

ROOT = Path(__file__).resolve().parents[1]
AUDIT_FILE = Path(os.getenv("IFCC_AUDIT_FILE", ROOT / "data" / "audit_log.jsonl"))
# Simple RBAC: key -> role. In production keys come from a secrets manager.
API_KEYS = {os.getenv("IFCC_OPS_KEY", "ops-demo-key"): "operations",
            os.getenv("IFCC_UW_KEY", "uw-demo-key"): "underwriter"}

app = FastAPI(title="IFCC Bank Credit Underwriting API", version=SC["model_version"])
STORE: dict = {}
_lock = threading.Lock()

# ---- observability (Step 19, 35): structured JSON logs + simple counters
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("ifcc")
METRICS = Counter()


@app.middleware("http")
async def log_requests(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    ms = round((time.perf_counter() - t0) * 1000, 1)
    METRICS["requests_total"] += 1
    METRICS[f"status_{response.status_code}"] += 1
    log.info(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "method": request.method,
                         "path": request.url.path, "status": response.status_code, "ms": ms}))
    return response


@app.get("/", include_in_schema=False)
def home():
    page = ROOT / "app" / "underwriting_desk.html"
    if page.exists():
        return HTMLResponse(page.read_text(encoding="utf-8"))
    return {"message": "IFCC API is running. Open /docs"}


@app.get("/metrics")
def metrics():
    decided = {k: v for k, v in METRICS.items() if k.startswith("decision_")}
    total = sum(decided.values()) or 1
    return {"counters": dict(METRICS),
            "approval_rate": round(METRICS["decision_APPROVE"] / total, 4),
            "referral_rate": round(METRICS["decision_REFER"] / total, 4),
            "overrides": METRICS["human_reviews"]}


# ------------------------------------------------------------------ schemas
class Application(BaseModel):
    employment_type: Literal["Salaried", "Self-Employed", "Contract", "Unemployed"]
    employment_years: Optional[float] = Field(None, ge=0, le=50)
    home_ownership: Literal["Own", "Mortgage", "Rent"]
    annual_income: float = Field(..., ge=0)
    credit_history_years: float = Field(..., ge=0, le=60)
    num_open_accounts: int = Field(..., ge=0)
    credit_utilization: Optional[float] = Field(None, ge=0, le=1)
    num_inquiries_6m: int = Field(..., ge=0)
    num_delinquencies_2y: int = Field(..., ge=0)
    existing_monthly_debt: float = Field(..., ge=0)
    loan_purpose: Literal["Debt Consolidation", "Home Improvement", "Medical",
                          "Education", "Wedding", "Travel", "Other"]
    loan_amount: float = Field(..., gt=0, le=100_000)
    loan_term_months: Literal[12, 24, 36, 48, 60]


class Review(BaseModel):
    final_decision: Literal["APPROVE", "DECLINE"]
    rationale: str = Field(..., min_length=10)
    reviewer_id: str


# ------------------------------------------------------------------ audit
def _last_hash() -> str:
    if not AUDIT_FILE.exists() or AUDIT_FILE.stat().st_size == 0:
        return "GENESIS"
    return json.loads(AUDIT_FILE.read_text().strip().splitlines()[-1])["hash"]


def audit(event: str, ref: str, actor: str, payload: dict):
    """Append-only, hash-chained audit event: editing any old line breaks the chain."""
    with _lock:
        AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, "ref": ref,
               "actor": actor, "model_version": SC["model_version"], "payload": payload,
               "prev_hash": _last_hash()}
        rec["hash"] = hashlib.sha256(json.dumps(rec, sort_keys=True, default=str).encode()).hexdigest()
        with AUDIT_FILE.open("a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        return rec["hash"]


def role_of(key: Optional[str]) -> str:
    if key not in API_KEYS:
        raise HTTPException(401, "invalid or missing X-API-Key")
    return API_KEYS[key]


# ------------------------------------------------------------------ routes
@app.get("/health")
def health():
    return {"status": "ok", "model_version": SC["model_version"]}


@app.post("/applications", status_code=201)
def create_application(appl: Application, x_api_key: Optional[str] = Header(None),
                       idempotency_key: Optional[str] = Header(None)):
    role = role_of(x_api_key)
    if idempotency_key:                                   # safe retries (Step 14)
        for rec in STORE.values():
            if rec.get("idempotency_key") == idempotency_key:
                return rec
    data = appl.model_dump()
    errs = validate(data)
    if errs:
        raise HTTPException(422, errs)
    ref = f"APP-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8].upper()}"
    result = score_application(data)
    status = {"APPROVE": "APPROVED", "DECLINE": "DECLINED", "REFER": "PENDING_REVIEW"}[result["decision"]]
    rec = {"application_ref": ref, "status": status, "input": data, "result": result,
           "idempotency_key": idempotency_key, "review": None}
    STORE[ref] = rec
    METRICS[f"decision_{result['decision']}"] += 1
    audit("APPLICATION_RECEIVED", ref, role, {"input": data})
    rec["audit_hash"] = audit("AUTOMATED_DECISION", ref, "underwriting-engine",
                              {k: result[k] for k in ("score", "pd_12m", "grade", "decision",
                                                      "policy_rules_fired", "reason_codes", "trace")})
    return rec


@app.get("/applications/{ref}")
def get_application(ref: str, x_api_key: Optional[str] = Header(None)):
    role_of(x_api_key)
    if ref not in STORE:
        raise HTTPException(404, "application not found")
    return STORE[ref]


@app.get("/review-queue")
def review_queue(x_api_key: Optional[str] = Header(None)):
    role_of(x_api_key)
    return [{"application_ref": r["application_ref"], "score": r["result"]["score"],
             "grade": r["result"]["grade"], "rules": r["result"]["policy_rules_fired"]}
            for r in STORE.values() if r["status"] == "PENDING_REVIEW"]


@app.post("/applications/{ref}/review")
def review(ref: str, rv: Review, x_api_key: Optional[str] = Header(None)):
    if role_of(x_api_key) != "underwriter":
        raise HTTPException(403, "only underwriters can review")
    rec = STORE.get(ref)
    if not rec:
        raise HTTPException(404, "application not found")
    if rec["status"] != "PENDING_REVIEW":
        raise HTTPException(409, f"application is {rec['status']}, not pending review")
    # Override control: policy DECLINE rules cannot be overridden to APPROVE
    if rv.final_decision == "APPROVE" and any(r["action"] == "DECLINE" for r in rec["result"]["policy_rules_fired"]):
        raise HTTPException(409, "policy decline rule fired; override not permitted")
    rec["status"] = "APPROVED" if rv.final_decision == "APPROVE" else "DECLINED"
    rec["review"] = rv.model_dump() | {"reviewed_at": datetime.now(timezone.utc).isoformat()}
    METRICS["human_reviews"] += 1
    rec["audit_hash"] = audit("HUMAN_REVIEW_DECISION", ref, f"underwriter:{rv.reviewer_id}", rec["review"])
    return rec


@app.get("/audit/verify")
def verify_audit(x_api_key: Optional[str] = Header(None)):
    role_of(x_api_key)
    if not AUDIT_FILE.exists():
        return {"valid": True, "events": 0}
    prev = "GENESIS"
    lines = AUDIT_FILE.read_text().strip().splitlines()
    for i, line in enumerate(lines):
        rec = json.loads(line)
        h = rec.pop("hash")
        if rec["prev_hash"] != prev or hashlib.sha256(json.dumps(rec, sort_keys=True, default=str).encode()).hexdigest() != h:
            return {"valid": False, "broken_at_line": i + 1, "events": len(lines)}
        prev = h
    return {"valid": True, "events": len(lines)}
