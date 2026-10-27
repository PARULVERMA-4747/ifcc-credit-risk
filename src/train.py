"""
IFCC Bank - Personal Loan Application Scorecard: end-to-end training pipeline.

Run:  python src/train.py
Produces: artifacts/ (model, binner, scorecard.json, metadata) and reports/ (metrics, tables, charts)
"""
import json, hashlib, sys
from pathlib import Path
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score, log_loss, brier_score_loss, roc_curve
from sklearn.calibration import calibration_curve

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C
from woe import WoEBinner

ROOT = Path(__file__).resolve().parents[1]
ART, REP = ROOT / "artifacts", ROOT / "reports"
ART.mkdir(exist_ok=True); REP.mkdir(exist_ok=True)

FACTOR = C.PDO / np.log(2)
OFFSET = C.BASE_SCORE - FACTOR * np.log(C.BASE_ODDS)


# ----------------------------------------------------------------- metrics
def ks_stat(y, p):
    fpr, tpr, _ = roc_curve(y, p)
    return float(np.max(tpr - fpr))


def psi(expected, actual, bins=10):
    edges = np.unique(np.quantile(expected, np.linspace(0, 1, bins + 1)))
    edges[0], edges[-1] = -np.inf, np.inf
    e = np.histogram(expected, edges)[0] / len(expected)
    a = np.histogram(actual, edges)[0] / len(actual)
    e, a = np.clip(e, 1e-6, None), np.clip(a, 1e-6, None)
    return float(np.sum((a - e) * np.log(a / e)))


def evaluate(y, p):
    auc = roc_auc_score(y, p)
    return {"auc": round(auc, 4), "gini": round(2 * auc - 1, 4), "ks": round(ks_stat(y, p), 4),
            "log_loss": round(log_loss(y, p), 4), "brier": round(brier_score_loss(y, p), 4)}


def pd_to_score(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.clip(OFFSET + FACTOR * np.log((1 - p) / p), C.SCORE_MIN, C.SCORE_MAX)


def grade(score):
    for g, lb in C.GRADES:
        if score >= lb:
            return g
    return C.GRADES[-1][0]


# ----------------------------------------------------------------- pipeline
def main():
    print("=" * 70, "\nIFCC Bank credit-risk pipeline |", C.MODEL_VERSION)

    # 1-2. Data + target
    df = pd.read_csv(ROOT / "data" / "applications.csv")
    data_hash = hashlib.sha256((ROOT / "data" / "applications.csv").read_bytes()).hexdigest()[:16]
    y = df[C.TARGET]
    features = [c for c in df.columns if c not in [C.TARGET, C.ID_COL] + C.EXCLUDED_FEATURES]
    X = df[features]
    print(f"[data] rows={len(df):,} features={len(features)} bad_rate={y.mean():.2%} (age excluded)")

    # data-quality report (Step 12)
    dq = pd.DataFrame({"dtype": X.dtypes.astype(str), "missing_pct": (X.isna().mean() * 100).round(2),
                       "n_unique": X.nunique()})
    dq.to_csv(REP / "data_quality.csv")

    # 5. Stratified split (do it BEFORE binning to avoid leakage)
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.30, stratify=y, random_state=C.SEED)

    # 3. WoE binning on train only
    binner = WoEBinner(max_bins=6).fit(Xtr, ytr, categorical=C.CATEGORICAL)
    iv = binner.iv_table()
    iv.to_csv(REP / "information_value.csv")
    print("[iv]\n" + iv.to_string())

    # 4. Feature selection
    selected = [f for f, v in binner.iv_.items() if v >= C.IV_MIN]
    flagged = [f for f, v in binner.iv_.items() if v > C.IV_SUSPICIOUS]
    print(f"[select] kept {len(selected)}/{len(features)}; suspicious (>0.5): {flagged or 'none'}")

    Wtr = binner.transform(Xtr)[selected]
    Wte = binner.transform(Xte)[selected]

    # 6a. Champion: logistic regression on WoE
    lr = LogisticRegression(C=1.0, max_iter=1000)
    lr.fit(Wtr, ytr)
    # sanity: with WoE = ln(good/bad), every coefficient should be NEGATIVE
    wrong_sign = [f for f, b in zip(selected, lr.coef_[0]) if b > 0]
    if wrong_sign:
        print(f"[select] dropping wrong-sign features {wrong_sign} and refitting")
        selected = [f for f in selected if f not in wrong_sign]
        Wtr, Wte = Wtr[selected], Wte[selected]
        lr.fit(Wtr, ytr)

    p_tr_lr = lr.predict_proba(Wtr)[:, 1]
    p_te_lr = lr.predict_proba(Wte)[:, 1]

    # 6b. Challenger: gradient boosting on raw features
    Xtr_gb, Xte_gb = Xtr.copy(), Xte.copy()
    for c in C.CATEGORICAL:
        cats = pd.Categorical(Xtr[c]).categories
        Xtr_gb[c] = pd.Categorical(Xtr[c], categories=cats).codes
        Xte_gb[c] = pd.Categorical(Xte[c], categories=cats).codes
    gb = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=31,
                                        categorical_features=[Xtr.columns.get_loc(c) for c in C.CATEGORICAL],
                                        random_state=C.SEED)
    gb.fit(Xtr_gb, ytr)
    p_te_gb = gb.predict_proba(Xte_gb)[:, 1]

    # 7. Evaluation
    metrics = {"champion_lr_woe": {"train": evaluate(ytr, p_tr_lr), "test": evaluate(yte, p_te_lr)},
               "challenger_gbm": {"test": evaluate(yte, p_te_gb)}}
    print("[eval]", json.dumps(metrics, indent=2))

    # decile rank-ordering on test
    dec = pd.DataFrame({"pd": p_te_lr, "y": yte.values})
    dec["decile"] = pd.qcut(dec.pd.rank(method="first"), 10, labels=range(10, 0, -1)).astype(int)
    dec_t = dec.groupby("decile").agg(n=("y", "size"), avg_pred_pd=("pd", "mean"),
                                      actual_bad_rate=("y", "mean")).sort_index()
    dec_t = dec_t.round(4)
    dec_t.to_csv(REP / "decile_table.csv")
    print("[deciles] (1 = riskiest)\n" + dec_t.to_string())

    # 8. Scorecard points
    b0 = lr.intercept_[0]
    k = len(selected)
    scorecard = {}
    rows = []
    for f, b in zip(selected, lr.coef_[0]):
        spec = binner.bins_[f]
        pts = {}
        for bin_label, w in spec["woe"].items():
            # logit_bad = b0 + sum b*w ;  score = OFFSET - FACTOR*logit_bad
            pts[bin_label] = round(float(OFFSET / k - FACTOR * (b * w + b0 / k)), 2)
            t = spec["table"].loc[bin_label]
            rows.append({"feature": f, "bin": bin_label, "count": int(t["count"]),
                         "bad_rate": round(float(t.bad_rate), 4), "woe": round(float(w), 4),
                         "points": pts[bin_label]})
        entry = {"type": spec["type"], "coef": float(b), "points": pts,
                 "neutral_points": round(float(OFFSET / k - FACTOR * (b0 / k)), 2)}
        if spec["type"] == "numeric":
            edges = spec["edges"]
            entry["bins"] = []
            for i in range(len(edges) - 1):
                lab = f"[{edges[i]:.4g}, {edges[i+1]:.4g})"
                entry["bins"].append({"label": lab,
                                      "lower": None if not np.isfinite(edges[i]) else float(edges[i]),
                                      "upper": None if not np.isfinite(edges[i + 1]) else float(edges[i + 1]),
                                      "points": pts.get(lab, entry["neutral_points"])})
            entry["missing_points"] = pts.get("__MISSING__", entry["neutral_points"])
        scorecard[f] = entry
    pd.DataFrame(rows).to_csv(REP / "scorecard_points.csv", index=False)

    score_tr, score_te = pd_to_score(p_tr_lr), pd_to_score(p_te_lr)

    # 9. Stability
    psi_val = psi(score_tr, score_te)
    metrics["psi_train_vs_test"] = round(psi_val, 4)
    print(f"[psi] train vs test score PSI = {psi_val:.4f} ({'stable' if psi_val < 0.1 else 'review'})")

    # grade table
    te = Xte.copy()
    te["y"], te["pd"], te["score"] = yte.values, p_te_lr, score_te
    te["grade"] = te.score.map(grade)
    g_t = te.groupby("grade").agg(n=("y", "size"), share=("y", lambda s: len(s) / len(te)),
                                  avg_pd=("pd", "mean"), bad_rate=("y", "mean"),
                                  min_score=("score", "min"), max_score=("score", "max")).round(4)
    g_t.to_csv(REP / "grade_table.csv")
    print("[grades]\n" + g_t.to_string())

    # 10. Business view: EL + cutoff strategy
    te["ead"] = te.loan_amount * C.EAD_FACTOR
    te["el"] = te.pd * C.LGD * te.ead
    cut_rows = []
    for cut in range(500, 611, 10):
        acc = te[te.score >= cut]
        cut_rows.append({"cutoff": cut, "approval_rate": round(len(acc) / len(te), 4),
                         "bad_rate_approved": round(acc.y.mean(), 4) if len(acc) else None,
                         "expected_loss_approved": round(acc.el.sum(), 0),
                         "actual_loss_approved": round((acc.y * C.LGD * acc.ead).sum(), 0),
                         "el_pct_of_book": round(acc.el.sum() / acc.ead.sum(), 4) if len(acc) else None})
    cut_t = pd.DataFrame(cut_rows)
    cut_t.to_csv(REP / "cutoff_strategy.csv", index=False)
    print("[cutoff]\n" + cut_t.to_string(index=False))
    metrics["portfolio_test"] = {"total_ead": round(te.ead.sum(), 0), "total_el": round(te.el.sum(), 0),
                                 "el_rate": round(te.el.sum() / te.ead.sum(), 4)}

    # Charts
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.5))
    for name, p in [("Champion LR-WoE", p_te_lr), ("Challenger GBM", p_te_gb)]:
        fpr, tpr, _ = roc_curve(yte, p); ax[0].plot(fpr, tpr, label=f"{name} AUC={roc_auc_score(yte, p):.3f}")
    ax[0].plot([0, 1], [0, 1], "k--", lw=0.8); ax[0].set_title("ROC (test)"); ax[0].legend()
    fp, mp = calibration_curve(yte, p_te_lr, n_bins=10, strategy="quantile")
    ax[1].plot(mp, fp, "o-"); ax[1].plot([0, 0.5], [0, 0.5], "k--", lw=0.8)
    ax[1].set_title("Calibration (test)"); ax[1].set_xlabel("predicted PD"); ax[1].set_ylabel("actual bad rate")
    ax[2].hist(score_te[yte == 0], bins=40, alpha=0.6, label="good", density=True)
    ax[2].hist(score_te[yte == 1], bins=40, alpha=0.6, label="bad", density=True)
    ax[2].axvline(C.APPROVE_CUTOFF, color="g", ls="--"); ax[2].axvline(C.REFER_CUTOFF, color="r", ls="--")
    ax[2].set_title("Score distribution (test)"); ax[2].legend()
    plt.tight_layout(); plt.savefig(REP / "model_charts.png", dpi=110); plt.close()

    # 11. Persist versioned artifacts
    joblib.dump({"binner": binner, "lr": lr, "selected": selected}, ART / "champion.joblib")
    joblib.dump(gb, ART / "challenger_gbm.joblib")
    meta = {"model_version": C.MODEL_VERSION, "trained_at_utc": datetime.now(timezone.utc).isoformat(),
            "data_sha256_16": data_hash, "seed": C.SEED, "n_train": len(Xtr), "n_test": len(Xte),
            "selected_features": selected, "excluded_features": C.EXCLUDED_FEATURES,
            "scaling": {"pdo": C.PDO, "base_score": C.BASE_SCORE, "base_odds": C.BASE_ODDS,
                        "factor": FACTOR, "offset": OFFSET},
            "metrics": metrics}
    (ART / "metadata.json").write_text(json.dumps(meta, indent=2))
    (REP / "metrics.json").write_text(json.dumps(metrics, indent=2))
    # portable scorecard for the web app / any non-Python system
    (ART / "scorecard.json").write_text(json.dumps({
        "model_version": C.MODEL_VERSION, "factor": FACTOR, "offset": OFFSET,
        "score_min": C.SCORE_MIN, "score_max": C.SCORE_MAX, "grades": C.GRADES,
        "approve_cutoff": C.APPROVE_CUTOFF, "refer_cutoff": C.REFER_CUTOFF, "lgd": C.LGD,
        "policy": C.POLICY, "features": scorecard}, indent=2))
    print(f"[done] artifacts -> {ART}\n" + "=" * 70)
    return metrics


if __name__ == "__main__":
    main()
