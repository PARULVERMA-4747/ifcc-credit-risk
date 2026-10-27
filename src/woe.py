"""
Weight of Evidence (WoE) binning and Information Value (IV).

WoE(bin) = ln( %good in bin / %bad in bin )
   > 0  -> bin is safer than average
   < 0  -> bin is riskier than average
IV = sum( (%good - %bad) * WoE )   -> how much a feature separates good vs bad
"""
import numpy as np
import pandas as pd

MISSING = "__MISSING__"


class WoEBinner:
    def __init__(self, max_bins: int = 6, min_bin_share: float = 0.05):
        self.max_bins = max_bins
        self.min_bin_share = min_bin_share
        self.bins_ = {}        # feature -> dict(type, edges/categories, woe map)
        self.iv_ = {}

    # ---------- helpers ---------------------------------------------------
    @staticmethod
    def _woe_table(x_binned: pd.Series, y: pd.Series) -> pd.DataFrame:
        t = pd.crosstab(x_binned, y).reindex(columns=[0, 1], fill_value=0)
        t.columns = ["good", "bad"]
        tg, tb = t.good.sum(), t.bad.sum()
        # +0.5 smoothing avoids log(0) for tiny bins
        pg = (t.good + 0.5) / (tg + 0.5 * len(t))
        pb = (t.bad + 0.5) / (tb + 0.5 * len(t))
        t["count"] = t.good + t.bad
        t["bad_rate"] = t.bad / t["count"]
        t["woe"] = np.log(pg / pb)
        t["iv_part"] = (pg - pb) * t.woe
        return t

    def _numeric_edges(self, x: pd.Series, y: pd.Series):
        """Quantile bins, then merge neighbours until bad-rate is monotonic."""
        xs = x.dropna()
        qs = np.unique(np.quantile(xs, np.linspace(0, 1, self.max_bins + 1)))
        edges = [-np.inf] + list(qs[1:-1]) + [np.inf]
        while len(edges) > 3:
            b = pd.cut(xs, edges, include_lowest=True)
            br = y.loc[xs.index].groupby(b, observed=False).mean().values
            d = np.diff(br)
            if np.all(d >= 0) or np.all(d <= 0):
                break
            # merge the pair of neighbours whose bad rates are closest
            i = int(np.argmin(np.abs(d)))
            edges.pop(i + 1)
        return edges

    # ---------- API -------------------------------------------------------
    def fit(self, X: pd.DataFrame, y: pd.Series, categorical: list):
        for col in X.columns:
            x = X[col]
            if col in categorical:
                xb = x.fillna(MISSING).astype(str)
                spec = {"type": "categorical"}
            else:
                edges = self._numeric_edges(x, y)
                xb = self._apply_numeric(x, edges)
                spec = {"type": "numeric", "edges": edges}
            t = self._woe_table(xb, y)
            spec["table"] = t
            spec["woe"] = t.woe.to_dict()
            self.bins_[col] = spec
            self.iv_[col] = float(t.iv_part.sum())
        return self

    @staticmethod
    def _apply_numeric(x: pd.Series, edges):
        labels = [f"[{edges[i]:.4g}, {edges[i+1]:.4g})" for i in range(len(edges) - 1)]
        b = pd.cut(x, edges, labels=labels, right=False).astype(object)
        return b.where(x.notna(), MISSING).astype(str)

    def bin_labels(self, X: pd.DataFrame) -> pd.DataFrame:
        out = {}
        for col, spec in self.bins_.items():
            if spec["type"] == "categorical":
                out[col] = X[col].fillna(MISSING).astype(str)
            else:
                out[col] = self._apply_numeric(X[col], spec["edges"])
        return pd.DataFrame(out, index=X.index)

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        B = self.bin_labels(X)
        out = {}
        for col, spec in self.bins_.items():
            # unseen category / empty missing bin -> neutral WoE 0
            out[col] = B[col].map(spec["woe"]).fillna(0.0).astype(float)
        return pd.DataFrame(out, index=X.index)

    def iv_table(self) -> pd.DataFrame:
        s = pd.Series(self.iv_).sort_values(ascending=False)
        def strength(v):
            return ("useless" if v < 0.02 else "weak" if v < 0.1 else
                    "medium" if v < 0.3 else "strong" if v <= 0.5 else "suspicious (>0.5)")
        return pd.DataFrame({"iv": s.round(4), "strength": s.map(strength)})
