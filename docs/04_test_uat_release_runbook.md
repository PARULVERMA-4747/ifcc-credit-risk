# Testing, UAT, Release and Runbook
Steps 16, 21–29, 35–39 and closure.

## Sprint plan (Step 16)
| Sprint | Epic | Stories |
|---|---|---|
| 1 | Data & model | generate data, WoE/IV, champion + challenger, metrics |
| 2 | Decisioning | scorecard scaling, grades, policy rules, reason codes, EL |
| 3 | Service | API, RBAC, review queue, audit chain, tests |
| 4 | Release | web desk, CI, Docker, Render deploy, docs |

## Automated tests (Steps 21–24) — `pytest -q`, 19 tests
| Area | Tests |
|---|---|
| Functional (21) | approve good, decline bad, validation, missing values |
| Integration (22) | health, create, idempotency, review queue, human review, audit verify |
| Decision validation (23) | monotonic utilisation, monotonic delinquencies, POL-01, POL-05, EL formula, trace sums to score, model thresholds |
| Security (24) | auth required, role check (ops cannot review), no age, tamper detection, no policy override |

## UAT scenarios (Step 25) — business user runs these in the web desk / `/docs`
| # | Scenario | Expected | Result | Signed |
|---|---|---|---|---|
| U1 | "Strong salaried" example | APPROVE, grade A/B, no reasons | | |
| U2 | "Borderline" example | REFER, grade D | | |
| U3 | "High risk" example | DECLINE with 4 reasons | | |
| U4 | "Large loan" example | REFER by POL-05 | | |
| U5 | Income 10,000 | DECLINE by POL-01 | | |
| U6 | Underwriter approves a REFER with rationale | status APPROVED, audit event | | |
| U7 | Audit verify after cases | valid = true | | |

## Release checklist (Steps 26–29)
- [ ] Version `ifcc-pl-scorecard-v1.0.0` tagged, release notes written
- [ ] CI green (tests, bandit, pip-audit)
- [ ] Render environment variables set (`IFCC_OPS_KEY`, `IFCC_UW_KEY`)
- [ ] Deploy; smoke test: `/health` ok, one application scored, `/audit/verify` valid
- [ ] Rollback plan: redeploy previous commit in Render ("Rollback" on last good deploy)
- [ ] Go / no-go recorded: date, sponsor, PO, open risks R1–R7 accepted

## Monitoring (Steps 35–36)
| What | Threshold | Action |
|---|---|---|
| `/health` down | any | restart / rollback |
| Error rate | > 1% | incident |
| Approval rate | outside 55–70% | review |
| Override rate | > 10% of REFER | review rules |
| Score PSI vs training | > 0.10 watch, > 0.25 act | model review |

## Incident steps (Step 37)
Log → severity (P1 down, P2 wrong decisions, P3 minor) → tell stakeholders → restore (rollback) → root cause → preventive action → postmortem.

## Model / rule change (Steps 38–39)
Change `src/config.py` or data → bump `MODEL_VERSION` → `python src/train.py` → `pytest` → PR review → CI → deploy → note in release log.

## Closure (Section 9)
Hand over: this repo, docs/, reports/, runbook above, known issues R1–R7. Archive test evidence (`pytest` output, reports/). Lessons learned meeting. Close after PO acceptance.
