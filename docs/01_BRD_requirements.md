# BRD — IFCC Bank Personal Loan Credit Risk Scorecard
Steps 1–5, 10 of the execution playbook. Version 1.0 · 27 Oct 2026

## 1. Business objective (Step 1)
| Item | Value |
|---|---|
| Problem | Manual personal-loan underwriting is slow, inconsistent and hard to explain |
| Target users | Branch/operations staff, underwriters, credit committee, risk, compliance |
| Outcome | Automated, explainable APPROVE / REFER / DECLINE in under 1 second |
| Scope (in) | Unsecured personal loans, application scorecard, policy rules, reason codes, EL, API, audit |
| Scope (out) | Secured loans, collections, LGD/EAD models, real bureau connection, reject inference |
| Success measures | Gini ≥ 0.40, KS ≥ 0.30, PSI < 0.10, decision < 1 s, 100% decisions audit-reconstructable |
| Regulatory constraints | Fair lending (no protected attributes such as age), adverse-action reasons, Basel/IFRS-9 style PD, SR 11-7 style model governance |

## 2. Stakeholder map (Step 2)
| Role | Who (simulated) | Decision rights |
|---|---|---|
| Business sponsor | Head of Retail Lending | Go/no-go, budget |
| Product owner | PL Product Manager | Scope, backlog priority, UAT sign-off |
| Credit / underwriting | Chief Credit Officer + underwriters | Policy rules, cutoffs, overrides |
| Risk / model validation | Model Risk team | Model approval, monitoring thresholds |
| Fraud | Fraud Ops | Fraud signals |
| Compliance | Compliance officer | Fair lending, adverse action wording |
| Operations | Loan ops | Intake process |
| Technology / Data / AI | Tech lead, data scientist | Architecture, model build |
| Security | InfoSec | RBAC, secrets, PII |

## 3. Current state (Step 3) — as-is
Customer fills paper/online form → ops checks documents → underwriter pulls bureau report → manual judgement → approval by hierarchy by amount → letter sent.
Pain points: 2–3 day turnaround, different decisions for similar files, no structured decline reasons, no audit of why.

## 4. Requirements (Step 4)
### Functional
| ID | Requirement | Priority (MoSCoW) | Acceptance criterion | Test |
|---|---|---|---|---|
| FR-01 | Capture 13 application fields and validate them | Must | Invalid input returns 422 with the field name | test_schema_validation_422, test_validation_rejects_bad_term |
| FR-02 | Compute DTI, EMI, loan-to-income | Must | Values returned in `derived` | test_good_applicant_approved |
| FR-03 | Return 12-month PD, score 300–900, grade A–E | Must | All present for every application | test_missing_values_handled |
| FR-04 | Decide APPROVE / REFER / DECLINE with configurable cutoffs | Must | Cutoffs read from config | test_good_applicant_approved, test_bad_applicant_declined_with_reasons |
| FR-05 | Apply hard policy & fraud rules over the model | Must | Rule fires → decision follows rule | test_policy_income_floor_declines, test_policy_large_loan_refers |
| FR-06 | Up to 4 adverse-action reason codes on non-approvals | Must | 1–4 reasons on DECLINE | test_bad_applicant_declined_with_reasons |
| FR-07 | Expected Loss = PD × LGD × EAD | Must | Formula holds | test_expected_loss_formula |
| FR-08 | Human review queue with override + rationale | Must | Only underwriter can review; rationale ≥ 10 chars | test_refer_then_human_review_and_audit |
| FR-09 | Policy DECLINE cannot be overridden to APPROVE | Must | 409 returned | test_cannot_override_policy_decline |
| FR-10 | Full decision trace (points per factor) | Must | Trace sums to score | test_trace_sums_to_score |
| FR-11 | Live web desk for demo | Should | Same score as API | parity check in build |
| FR-12 | Disparate-impact report across protected groups | Could (later release) | — | — |

### Non-functional
| ID | Requirement | Acceptance |
|---|---|---|
| NFR-01 | Explainable, monotonic model | Monotonic tests pass |
| NFR-02 | No protected attributes in model | test_age_not_used |
| NFR-03 | Tamper-evident audit | test_tamper_detected |
| NFR-04 | Idempotent create | test_idempotent_create |
| NFR-05 | Auth on all business endpoints | test_auth_required |
| NFR-06 | Reproducible build (seed, data hash, version) | artifacts/metadata.json |

## 5. Assumptions
- Synthetic data stands in for real history; bureau, document and notification systems are simulated.
- LGD fixed at 65%, EAD = loan amount, EMI at 14% APR.

## 10. MVP baseline
MVP = FR-01 … FR-11 + NFR-01 … NFR-06. FR-12 and real integrations are Release 2.
