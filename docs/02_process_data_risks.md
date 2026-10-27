# Process, Data Dictionary and Risk Register
Steps 6, 8, 9, 12 of the execution playbook.

## To-be process (Step 6)
Intake (API / web form) → validate fields → derive DTI, EMI, LTI → WoE bin each factor → scorecard points → score, PD, grade → policy + fraud rules → decision (strictest wins) → APPROVE / REFER (review queue → underwriter) / DECLINE (reason codes) → audit event every step.

## Data dictionary (Step 8)
| Field | Type | Source | Used in model | Notes |
|---|---|---|---|---|
| application_id | string | system | no | unique reference |
| age | int | application | **no (protected)** | eligibility only |
| employment_type | category | application | yes | Salaried / Self-Employed / Contract / Unemployed |
| employment_years | float | application | yes | ~2% missing → own bin |
| home_ownership | category | application | no (IV 0.009) | |
| annual_income | float | application / documents | yes | |
| credit_history_years | float | bureau | yes | |
| num_open_accounts | int | bureau | no (IV 0.000) | |
| credit_utilization | 0–1 | bureau | yes | ~3% missing → own bin |
| num_inquiries_6m | int | bureau | yes | |
| num_delinquencies_2y | int | bureau | yes | |
| existing_monthly_debt | float | bureau | no directly (feeds DTI) | |
| loan_purpose | category | application | no (IV 0.010) | |
| loan_amount | float | application | no directly (feeds LTI, EAD) | |
| loan_term_months | 12/24/36/48/60 | application | yes | |
| dti | derived | (existing debt + new EMI) / monthly income | yes | |
| loan_to_income | derived | loan / annual income | yes | |
| default_12m | 0/1 | performance | target | 1 = serious delinquency/default in 12 m |

Retention: application + decision + audit kept 7 years (assumption, confirm with Compliance).

## Data quality checks (Step 12)
Generated in `reports/data_quality.csv`: type, % missing, unique count per field. Schema validation in `src/api.py` rejects out-of-range values.

## Risk & gap register (Step 9)
| ID | Risk / gap | Impact | Mitigation | Owner |
|---|---|---|---|---|
| R1 | Synthetic data overstates performance | High | Revalidate on real data, out-of-time sample | Model Risk |
| R2 | No reject inference (only approved loans have outcomes) | Medium | Add in Release 2 | Data Science |
| R3 | Bureau / document integrations simulated | High | Adapter interface; integrate in Release 2 | Tech Lead |
| R4 | Disparate impact not tested (no protected groups in data) | High | Fairness report before real go-live | Compliance |
| R5 | In-memory application store lost on restart | Medium | Move to Postgres before production | Engineering |
| R6 | Demo API keys | High | Secrets manager + SSO | Security |
| R7 | Population drift | Medium | Monthly PSI, review if > 0.25 | Risk |
