# Solution Architecture, API and Security
Steps 11, 13, 14, 15.

## Layers (Step 11)
| Layer | Component | File |
|---|---|---|
| UI | Underwriting Desk web page (served at `/`) | `app/underwriting_desk.html` |
| API | FastAPI service | `src/api.py` |
| Decision engine | Scorecard + policy rules + fraud signals + reason codes | `src/score.py` |
| Model | WoE binner + logistic regression (champion), GBM (challenger) | `src/woe.py`, `src/train.py` |
| Config | Governed numbers (cutoffs, grades, rules, LGD) | `src/config.py` |
| Data | Applications, audit log | `data/` |
| Artifacts | Versioned model + metadata + portable scorecard | `artifacts/` |
| CI/CD | GitHub Actions, Docker, Render | `.github/workflows/ci.yml`, `Dockerfile`, `render.yaml` |

## Decisioning design (Step 13)
- The model produces evidence (score, PD, trace). Governed rules and authorised underwriters control the outcome.
- Final decision = strictest of {model band, every fired rule}.
- Human-review triggers: score 530–549, POL-03, POL-04, POL-05, FRD-01.
- Override control: underwriter may APPROVE/DECLINE a REFER with written rationale; policy DECLINE cannot be overridden.

## API contract (Step 14)
| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | /health | public | liveness + model version |
| POST | /applications | operations, underwriter | intake + automated decision; header `Idempotency-Key` for safe retries |
| GET | /applications/{ref} | any | fetch record |
| GET | /review-queue | any | REFER cases |
| POST | /applications/{ref}/review | underwriter | human decision |
| GET | /audit/verify | any | verify hash chain |

Errors: 401 no/invalid key · 403 wrong role · 404 unknown ref · 409 invalid state or forbidden override · 422 invalid input.

## Security & compliance (Step 15)
- RBAC by API key → role (operations / underwriter). Keys from environment variables `IFCC_OPS_KEY`, `IFCC_UW_KEY`.
- Secrets never in code for production; set them in Render's environment settings.
- No PII in this dataset; protected attribute `age` excluded from model.
- Audit log is append-only and hash-chained: changing any old line breaks verification.
- Environment separation: local (VS Code) → CI → Render.
