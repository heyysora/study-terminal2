"""Setup-outcome classifier, used only where it measurably helps.

Training data: backtest trades (features at the signal bar -> did the trade make money).
Validation: strictly chronological. Train on the earliest 70%, test on the latest 30% the
model never saw. No random shuffling, because shuffled financial data leaks the future.

Deployment rule: the model's probability is shown with signals only if, on the unseen test
period, it beats the naive "always predict the base win rate" forecast (Brier skill > 0.02)
and ranks trades better than chance (ROC AUC > 0.55), with at least 40 test trades.
Otherwise it's saved as 'not deployed' along with the reason, and signals use rules only.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

from ..backtest.engine import ML_FEATURES

SETUP_COLS = ["vwap_reclaim", "vwap_rejection", "orb_long", "orb_short", "level_breakout", "level_breakdown",
              "trend_pullback_long", "trend_pullback_short", "failed_breakdown", "failed_breakout"]


def to_xy(trades: list[dict]) -> tuple[pd.DataFrame, np.ndarray, pd.Series]:
    rows, y, ts = [], [], []
    for t in trades:
        f = dict(t["features"])
        for s in SETUP_COLS:
            f[f"setup_{s}"] = 1.0 if t["setup"] == s else 0.0
        f["is_long"] = 1.0 if t["direction"] == "long" else 0.0
        rows.append(f)
        y.append(1 if t["pnl"] > 0 else 0)
        ts.append(pd.Timestamp(t["signal_ts"]))
    X = pd.DataFrame(rows)
    cols = ML_FEATURES + [f"setup_{s}" for s in SETUP_COLS] + ["is_long"]
    for c in cols:
        if c not in X:
            X[c] = np.nan
    return X[cols].astype(float), np.array(y), pd.Series(ts)


def _models() -> dict:
    out = {
        "logistic_baseline": make_pipeline(SimpleImputer(keep_empty_features=True), StandardScaler(), LogisticRegression(max_iter=500)),
        "random_forest": make_pipeline(SimpleImputer(keep_empty_features=True), RandomForestClassifier(n_estimators=300, min_samples_leaf=10, random_state=0)),
        "gradient_boosting": HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, min_samples_leaf=20, random_state=0),
    }
    try:  # optional: used only if you pip install xgboost
        from xgboost import XGBClassifier
        out["xgboost"] = XGBClassifier(n_estimators=200, max_depth=3, learning_rate=0.05, subsample=0.8, eval_metric="logloss")
    except Exception:
        pass
    return out


def calibration_table(y: np.ndarray, p: np.ndarray, bins: int = 5) -> list[dict]:
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        m = (p >= a) & (p < b if b < 1 else p <= b)
        if m.sum():
            out.append({"bin": f"{a:.1f}-{b:.1f}", "n": int(m.sum()), "predicted": round(float(p[m].mean()), 3),
                        "actual": round(float(y[m].mean()), 3)})
    return out


def psi(expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float:
    """Population stability index: >0.25 = big shift, 0.1-0.25 = moderate."""
    expected, actual = expected[~np.isnan(expected)], actual[~np.isnan(actual)]
    if len(expected) < 10 or len(actual) < 10:
        return float("nan")
    qs = np.unique(np.quantile(expected, np.linspace(0, 1, bins + 1)))
    if len(qs) < 3:
        return 0.0
    e = np.histogram(expected, qs)[0] / len(expected) + 1e-6
    a = np.histogram(np.clip(actual, qs[0], qs[-1]), qs)[0] / len(actual) + 1e-6
    return float(np.sum((a - e) * np.log(a / e)))


def train(trades: list[dict], model_dir: Path, test_frac: float = 0.3) -> dict:
    model_dir.mkdir(parents=True, exist_ok=True)
    if len(trades) < 60:
        return {"deployed": False, "reason": f"Only {len(trades)} trades; need at least 60 to train and test honestly.", "n": len(trades)}
    X, y, ts = to_xy(trades)
    order = np.argsort(ts.values)
    X, y, ts = X.iloc[order].reset_index(drop=True), y[order], ts.iloc[order].reset_index(drop=True)
    cut = int(len(X) * (1 - test_frac))
    usable = [c for c in X.columns if X[c].iloc[:cut].notna().any()]  # drop features never observed in training
    X = X[usable]
    Xtr, Xte, ytr, yte = X.iloc[:cut], X.iloc[cut:], y[:cut], y[cut:]
    if len(set(ytr)) < 2 or len(set(yte)) < 2:
        return {"deployed": False, "reason": "Training or test period has only winners or only losers.", "n": len(trades)}
    base = float(ytr.mean())
    brier_base = brier_score_loss(yte, np.full(len(yte), base))
    results = {}
    for name, m in _models().items():
        m.fit(Xtr, ytr)
        p = m.predict_proba(Xte)[:, 1]
        b = brier_score_loss(yte, p)
        results[name] = {"model": m, "brier": round(b, 4), "brier_skill": round(1 - b / brier_base, 4),
                         "auc": round(roc_auc_score(yte, p), 4), "precision": round(precision_score(yte, p >= 0.5, zero_division=0), 3),
                         "recall": round(recall_score(yte, p >= 0.5, zero_division=0), 3), "proba": p}
    best_name = max(results, key=lambda k: results[k]["brier_skill"])
    best = results[best_name]
    deployed = best["brier_skill"] > 0.02 and best["auc"] > 0.55 and len(yte) >= 40
    reason = ("Beats the base-rate forecast on unseen data." if deployed else
              f"Not deployed: best model ({best_name}) Brier skill {best['brier_skill']}, AUC {best['auc']} on {len(yte)} unseen trades "
              "- not reliably better than simply knowing the average win rate.")
    imp = permutation_importance(best["model"], Xte, yte, n_repeats=5, random_state=0, scoring="neg_brier_score")
    importance = sorted(({"feature": c, "importance": round(float(v), 5)} for c, v in zip(X.columns, imp.importances_mean)),
                        key=lambda d: -d["importance"])[:12]
    version = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    meta = {
        "version": version, "model": best_name, "deployed": deployed, "reason": reason,
        "n_train": int(len(ytr)), "n_test": int(len(yte)),
        "train_period": [str(ts.iloc[0]), str(ts.iloc[cut - 1])], "test_period": [str(ts.iloc[cut]), str(ts.iloc[-1])],
        "base_win_rate_train": round(base, 3), "win_rate_test": round(float(yte.mean()), 3), "brier_baseline": round(brier_base, 4),
        "candidates": {k: {kk: v[kk] for kk in ("brier", "brier_skill", "auc", "precision", "recall")} for k, v in results.items()},
        "calibration": calibration_table(yte, best["proba"]), "feature_importance": importance,
        "features": list(X.columns), "train_feature_sample": {c: X[c].iloc[:cut].dropna().tolist()[-500:] for c in ML_FEATURES if c in X},
    }
    joblib.dump(best["model"], model_dir / f"model-{version}.joblib")
    (model_dir / f"model-{version}.json").write_text(json.dumps(meta, indent=1, default=str))
    (model_dir / "latest.json").write_text(json.dumps({"version": version}))
    return {k: v for k, v in meta.items() if k != "train_feature_sample"}


class ModelRegistry:
    def __init__(self, model_dir: Path):
        self.dir = model_dir
        self._model = None
        self._meta: dict | None = None

    def load(self) -> dict | None:
        latest = self.dir / "latest.json"
        if not latest.exists():
            return None
        v = json.loads(latest.read_text())["version"]
        self._meta = json.loads((self.dir / f"model-{v}.json").read_text())
        self._model = joblib.load(self.dir / f"model-{v}.joblib") if self._meta.get("deployed") else None
        return self._meta

    @property
    def meta(self) -> dict | None:
        return {k: v for k, v in self._meta.items() if k != "train_feature_sample"} if self._meta else None

    def predict(self, features: dict, setup: str, direction: str) -> dict | None:
        if self._model is None:
            return None
        X, _, _ = to_xy([{"features": features, "setup": setup, "direction": direction, "pnl": 0, "signal_ts": "2000-01-01"}])
        p = float(self._model.predict_proba(X[self._meta["features"]])[:, 1][0])
        return {"probability_of_profit": round(p, 3), "model_version": self._meta["version"],
                "test_brier_skill": self._meta["candidates"][self._meta["model"]]["brier_skill"],
                "note": "Model estimate from historical setups, calibrated on unseen data. Not a guarantee."}

    def drift(self, recent_features: list[dict]) -> dict:
        if not self._meta or not recent_features:
            return {"available": False}
        rec = pd.DataFrame(recent_features)
        out = {}
        for c, sample in self._meta.get("train_feature_sample", {}).items():
            if c in rec:
                v = psi(np.array(sample, dtype=float), rec[c].astype(float).to_numpy())
                if v == v:
                    out[c] = round(v, 3)
        worst = max(out.values()) if out else 0
        return {"available": True, "psi": out, "status": "major drift" if worst > 0.25 else "moderate drift" if worst > 0.1 else "stable",
                "note": "PSI compares today's signal conditions with the training data. Drift means the model is seeing unfamiliar markets."}
