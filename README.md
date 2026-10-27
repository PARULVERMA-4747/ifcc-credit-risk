# IFCC Bank — Personal Loan Credit Risk Scorecard

Synthetic data only (no real PII). End-to-end: data → WoE/IV → logistic scorecard (champion) vs gradient boosting (challenger) → 300–900 score + grade A–E → policy rules → APPROVE / REFER / DECLINE → reason codes → Expected Loss → FastAPI with human review and tamper-evident audit.

## Run it (5 commands)

```bash
pip install -r requirements.txt
python src/generate_data.py          # 25,000 synthetic applications -> data/
python src/train.py                  # models, reports/, artifacts/
pytest -q                            # 19 tests
uvicorn src.api:app --reload         # open http://127.0.0.1:8000/docs
```

Demo API keys: `ops-demo-key` (operations), `uw-demo-key` (underwriter). Send as header `X-API-Key`.

## Results (test set, 7,500 applications)

| Metric | Champion LR-WoE | Challenger GBM |
|---|---|---|
| AUC | 0.743 | 0.730 |
| Gini | 0.486 | 0.460 |
| KS | 0.364 | 0.354 |
| PSI train vs test | 0.003 | – |

Cutoff 550 → 62% approval, 5.2% bad rate among approved (vs 10.6% overall).

## Folder map

| Path | What |
|---|---|
| `src/config.py` | every governed number: cutoffs, grades, PDO, LGD, policy rules |
| `src/generate_data.py` | synthetic data (swap for a real loader) |
| `src/woe.py` | Weight of Evidence binning + Information Value |
| `src/train.py` | full training + evaluation pipeline |
| `src/score.py` | scoring + decision engine (uses only `artifacts/scorecard.json`) |
| `src/api.py` | FastAPI service, review queue, RBAC, hash-chained audit log |
| `tests/` | functional, decision, integration and security tests |
| `reports/` | IV, deciles, grades, cutoff strategy, charts |
| `artifacts/` | versioned model files + metadata |
