"""Machine-learning engine (scikit-learn).

Every supervised result reports holdout or cross-validated metrics next to a
naive baseline so performance claims are always grounded in the supplied data.
Trained models live in an in-memory LRU store (not persisted; pickles are never
loaded from disk).
"""
from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, model_validator
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.ensemble import GradientBoostingClassifier, IsolationForest, RandomForestClassifier, RandomForestRegressor
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LinearRegression, LogisticRegression, Ridge
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
    silhouette_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_predict, train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight

from app.core.contracts import EngineError, ExecutionContext, OpResult
from app.core.engine import BaseEngine, operation
from app.engines.common import RecordsInput, load_frame, numeric_matrix, to_jsonable

MAX_MODELS = 20


class SupervisedInput(RecordsInput):
    target: str
    features: list[str] | None = None
    test_size: float = Field(0.25, gt=0.05, lt=0.6)
    random_state: int = 42
    predict: list[dict[str, Any]] | None = Field(None, max_length=10_000, description="Rows to score after training")


class ClassifyInput(SupervisedInput):
    model: Literal["random_forest", "logistic_regression", "gradient_boosting"] = "random_forest"


class RegressInput(SupervisedInput):
    model: Literal["random_forest", "linear", "ridge"] = "random_forest"


class PredictInput(BaseModel):
    model_id: str
    records: list[dict[str, Any]] = Field(..., min_length=1, max_length=10_000)


class ClusterInput(RecordsInput):
    features: list[str] | None = None
    k: int | None = Field(None, ge=2, le=20, description="Clusters; omit to choose 2-8 by silhouette")
    random_state: int = 42


class AnomalyInput(RecordsInput):
    features: list[str] | None = None
    id_field: str | None = None
    contamination: float | Literal["auto"] = Field(0.05, description="Expected anomaly share (0.001-0.5) or 'auto'")
    random_state: int = 42

    @model_validator(mode="after")
    def _check(self):
        if self.contamination != "auto" and not 0.001 <= float(self.contamination) <= 0.5:
            raise ValueError("contamination must be in [0.001, 0.5] or 'auto'")
        return self


class ForecastInput(BaseModel):
    values: list[float] = Field(..., min_length=8, max_length=100_000)
    timestamps: list[str] | None = None
    horizon: int = Field(12, ge=1, le=1000)
    season_length: int | None = Field(None, ge=2, le=10_000, description="e.g. 24 for hourly data with a daily cycle")
    holdout: int | None = Field(None, ge=1, description="Points held out for backtesting (default: horizon, capped at 25% of history)")


class TextClassifyInput(BaseModel):
    texts: list[str] = Field(..., min_length=4, max_length=50_000)
    labels: list[str] = Field(..., min_length=4, max_length=50_000)
    predict: list[str] | None = Field(None, max_length=10_000)
    random_state: int = 42

    @model_validator(mode="after")
    def _check(self):
        if len(self.texts) != len(self.labels):
            raise ValueError("texts and labels must have the same length")
        return self


class EvaluateInput(BaseModel):
    task: Literal["classification", "regression"]
    y_true: list[Any] = Field(..., min_length=1)
    y_pred: list[Any] = Field(..., min_length=1)


class EmptyInput(BaseModel):
    pass


def _clf_metrics(y_true, y_pred, labels) -> dict[str, Any]:
    return {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "precision_macro": round(float(precision_score(y_true, y_pred, average="macro", zero_division=0)), 4),
        "recall_macro": round(float(recall_score(y_true, y_pred, average="macro", zero_division=0)), 4),
        "f1_macro": round(float(f1_score(y_true, y_pred, average="macro", zero_division=0)), 4),
        "labels": [to_jsonable(x) for x in labels],
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
    }


def _fit_balanced(model, X, y) -> None:
    """Fit with 'balanced' sample weights (works for plain estimators and pipelines alike)."""
    w = compute_sample_weight("balanced", np.asarray(y, dtype=object))
    if hasattr(model, "steps"):
        model.fit(X, y, **{f"{model.steps[-1][0]}__sample_weight": w})
    else:
        model.fit(X, y, sample_weight=w)


def _reg_metrics(y_true, y_pred) -> dict[str, float]:
    return {
        "mae": round(float(mean_absolute_error(y_true, y_pred)), 4),
        "rmse": round(float(np.sqrt(mean_squared_error(y_true, y_pred))), 4),
        "r2": round(float(r2_score(y_true, y_pred)), 4) if len(y_true) > 1 else None,
    }


class MLEngine(BaseEngine):
    name = "ml"
    title = "Machine Learning Engine"
    description = "Classification, regression, clustering, anomaly detection, forecasting, text classification and evaluation."

    def __init__(self, store=None) -> None:
        super().__init__()
        self.store = store
        self._models: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def health(self) -> dict:
        h = super().health()
        h["models_in_memory"] = len(self._models)
        return h

    def _keep(self, entry: dict[str, Any]) -> str:
        model_id = uuid.uuid4().hex[:12]
        self._models[model_id] = {**entry, "created": time.time()}
        while len(self._models) > MAX_MODELS:
            self._models.popitem(last=False)
        return model_id

    # ---------------------------------------------------------------- supervised
    def _prepare(self, data: SupervisedInput):
        df = load_frame(data, self.store)
        if data.target not in df.columns:
            raise EngineError("UNKNOWN_TARGET", f"Target '{data.target}' not in columns", details={"available": list(df.columns)})
        df = df[df[data.target].notna()]
        if len(df) < 10:
            raise EngineError("TOO_FEW_ROWS", "Need at least 10 labelled rows")
        pred_df = pd.DataFrame.from_records(data.predict) if data.predict else pd.DataFrame()
        features = data.features or [c for c in df.columns if c != data.target]
        combined = pd.concat([df[features], pred_df.reindex(columns=features)], ignore_index=True) if len(pred_df) else df[features]
        X_all, cols = numeric_matrix(combined, features)
        X, X_pred = X_all.iloc[: len(df)], X_all.iloc[len(df):]
        return df, X, X_pred, cols, df[data.target]

    @operation("classify", ClassifyInput, description="Train/evaluate a tabular classifier; optionally score new rows")
    def op_classify(self, data: ClassifyInput, ctx: ExecutionContext) -> OpResult:
        df, X, X_pred, cols, y = self._prepare(data)
        y = y.astype(str)
        counts = y.value_counts()
        if len(counts) < 2:
            raise EngineError("ONE_CLASS", "Target needs at least two classes")
        stratify = y if counts.min() >= 2 else None
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=data.test_size, random_state=data.random_state, stratify=stratify)
        if data.model == "random_forest":
            model = RandomForestClassifier(n_estimators=200, random_state=data.random_state)
        elif data.model == "gradient_boosting":
            model = GradientBoostingClassifier(random_state=data.random_state)
        else:
            model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
        _fit_balanced(model, X_tr, y_tr)
        y_hat = model.predict(X_te)
        labels = sorted(y.unique())
        metrics = _clf_metrics(y_te, y_hat, labels)
        majority = y_tr.value_counts().idxmax()
        metrics["baseline_majority_accuracy"] = round(float((y_te == majority).mean()), 4)
        if len(labels) == 2:
            pos = labels[1]
            proba = model.predict_proba(X_te)[:, list(model.classes_).index(pos)]
            if y_te.nunique() == 2:
                metrics["roc_auc"] = round(float(roc_auc_score((y_te == pos).astype(int), proba)), 4)
        importances = self._importances(model, cols)
        model_id = self._keep({"task": "classification", "model": model, "columns": cols, "features": data.features
                               or [c for c in df.columns if c != data.target]})
        result: dict[str, Any] = {"model_id": model_id, "model": data.model, "rows": len(df), "train_rows": len(X_tr),
                                  "test_rows": len(X_te), "class_counts": {k: int(v) for k, v in counts.items()},
                                  "metrics": metrics, "feature_importance": importances}
        confidence = None
        if len(X_pred):
            preds = self._predict_rows(model, X_pred)
            result["predictions"] = preds
            confidence = round(float(np.mean([p["probability"] for p in preds])), 4)
        return OpResult(result=result, confidence=confidence, metadata={
            "evaluation": f"stratified holdout ({int(data.test_size * 100)}%)" if stratify is not None else "random holdout",
            "confidence_basis": "mean uncalibrated max class probability over scored rows" if confidence is not None else None})

    @staticmethod
    def _predict_rows(model, X_pred) -> list[dict[str, Any]]:
        proba = model.predict_proba(X_pred)
        classes = [str(c) for c in model.classes_]
        out = []
        for row in proba:
            i = int(np.argmax(row))
            out.append({"label": classes[i], "probability": round(float(row[i]), 4),
                        "probabilities": {c: round(float(p), 4) for c, p in zip(classes, row)}})
        return out

    @staticmethod
    def _importances(model, cols: list[str]) -> list[dict[str, Any]]:
        est = model[-1] if hasattr(model, "steps") else model
        if hasattr(est, "feature_importances_"):
            vals = est.feature_importances_
        elif hasattr(est, "coef_"):
            vals = np.abs(np.atleast_2d(est.coef_)).mean(axis=0)
        else:
            return []
        total = float(np.sum(vals)) or 1.0
        pairs = sorted(zip(cols, vals), key=lambda p: -p[1])[:15]
        return [{"feature": c, "importance": round(float(v) / total, 4)} for c, v in pairs]

    @operation("regress", RegressInput, description="Train/evaluate a regression model; optionally predict new rows")
    def op_regress(self, data: RegressInput, ctx: ExecutionContext) -> OpResult:
        df, X, X_pred, cols, y = self._prepare(data)
        y = pd.to_numeric(y, errors="coerce")
        mask = y.notna()
        X, y = X[mask.values], y[mask]
        X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=data.test_size, random_state=data.random_state)
        model = {"random_forest": RandomForestRegressor(n_estimators=200, random_state=data.random_state),
                 "linear": make_pipeline(StandardScaler(), LinearRegression()),
                 "ridge": make_pipeline(StandardScaler(), Ridge())}[data.model]
        model.fit(X_tr, y_tr)
        metrics = _reg_metrics(y_te, model.predict(X_te))
        metrics["baseline_mean_mae"] = round(float(mean_absolute_error(y_te, np.full(len(y_te), y_tr.mean()))), 4)
        model_id = self._keep({"task": "regression", "model": model, "columns": cols,
                               "features": data.features or [c for c in df.columns if c != data.target]})
        result: dict[str, Any] = {"model_id": model_id, "model": data.model, "rows": int(mask.sum()), "metrics": metrics,
                                  "feature_importance": self._importances(model, cols)}
        if len(X_pred):
            result["predictions"] = [round(float(v), 4) for v in model.predict(X_pred)]
        return OpResult(result=result, metadata={"evaluation": f"random holdout ({int(data.test_size * 100)}%)"})

    @operation("predict", PredictInput, description="Score rows with a model trained earlier in this process")
    def op_predict(self, data: PredictInput, ctx: ExecutionContext) -> OpResult:
        entry = self._models.get(data.model_id)
        if entry is None:
            raise EngineError("MODEL_NOT_FOUND", "Model not in memory (models are not persisted across restarts)", 404)
        df = pd.DataFrame.from_records(data.records).reindex(columns=entry["features"])
        X, cols = numeric_matrix(df, entry["features"])
        X = X.reindex(columns=entry["columns"], fill_value=0.0)
        if entry["task"] == "classification":
            preds = self._predict_rows(entry["model"], X)
            return OpResult(result={"predictions": preds}, confidence=round(float(np.mean([p["probability"] for p in preds])), 4),
                            metadata={"confidence_basis": "mean uncalibrated max class probability"})
        return OpResult(result={"predictions": [round(float(v), 4) for v in entry["model"].predict(X)]})

    # ---------------------------------------------------------------- unsupervised
    @operation("cluster", ClusterInput, description="K-means clustering (auto-k by silhouette) with a 2-D PCA projection")
    def op_cluster(self, data: ClusterInput, ctx: ExecutionContext) -> OpResult:
        df = load_frame(data, self.store)
        X, cols = numeric_matrix(df, data.features)
        if len(X) < 4:
            raise EngineError("TOO_FEW_ROWS", "Need at least 4 rows to cluster")
        Xs = StandardScaler().fit_transform(X)
        scores = {}
        if data.k:
            ks = [min(data.k, len(X) - 1)]
        else:
            ks = list(range(2, min(8, len(X) - 1) + 1))
        best = None
        for k in ks:
            km = KMeans(n_clusters=k, n_init=10, random_state=data.random_state).fit(Xs)
            s = silhouette_score(Xs, km.labels_) if len(set(km.labels_)) > 1 else -1
            scores[k] = round(float(s), 4)
            if best is None or s > best[0]:
                best = (s, k, km)
        _, k, km = best
        labels = km.labels_.tolist()
        proj = PCA(n_components=2, random_state=data.random_state).fit_transform(Xs) if Xs.shape[1] >= 2 else np.c_[Xs[:, 0], np.zeros(len(Xs))]
        centroids = []
        for c in range(k):
            members = X[np.array(labels) == c]
            centroids.append({"cluster": c, "size": len(members),
                              "centroid": {col: round(float(v), 4) for col, v in members.mean().items()}})
        return OpResult(result={"k": k, "labels": labels, "silhouette": scores[k], "silhouette_by_k": scores,
                                "clusters": centroids,
                                "projection": [{"x": round(float(a), 4), "y": round(float(b), 4), "cluster": int(l)}
                                               for (a, b), l in zip(proj, labels)]},
                        metadata={"features_used": cols})

    @operation("anomaly", AnomalyInput, description="Isolation Forest anomaly detection with per-row feature deviation explanations")
    def op_anomaly(self, data: AnomalyInput, ctx: ExecutionContext) -> OpResult:
        df = load_frame(data, self.store)
        exclude = {data.id_field} if data.id_field else set()
        X, cols = numeric_matrix(df, data.features, exclude=exclude)
        if len(X) < 8:
            raise EngineError("TOO_FEW_ROWS", "Need at least 8 rows for anomaly detection")
        contamination = data.contamination if data.contamination == "auto" else float(data.contamination)
        forest = IsolationForest(n_estimators=300, contamination=contamination, random_state=data.random_state).fit(X)
        raw = -forest.score_samples(X)  # higher = more anomalous
        flags = forest.predict(X) == -1
        lo, hi = float(raw.min()), float(raw.max())
        norm = (raw - lo) / ((hi - lo) or 1.0)
        med = X.median()
        mad = (X - med).abs().median().replace(0, np.nan)
        robust_z = ((X - med) / (1.4826 * mad)).fillna(0.0)
        rows = []
        for i in range(len(X)):
            z = robust_z.iloc[i]
            top = z.abs().sort_values(ascending=False).head(3)
            rows.append({
                "index": i,
                "id": to_jsonable(df.iloc[i][data.id_field]) if data.id_field else i,
                "anomaly_score": round(float(norm[i]), 4),
                "is_anomaly": bool(flags[i]),
                "top_deviations": [{"feature": f, "robust_z": round(float(z[f]), 2), "value": to_jsonable(X.iloc[i][f])}
                                   for f in top.index if abs(z[f]) >= 2],
            })
        return OpResult(result={"rows": rows, "anomaly_count": int(flags.sum()), "total": len(rows), "features_used": cols},
                        metadata={"method": "IsolationForest(n_estimators=300)", "contamination": contamination,
                                  "score_note": "anomaly_score is min-max normalised within this batch; not a probability"})

    # ---------------------------------------------------------------- forecasting
    @operation("forecast", ForecastInput, description="Backtested model selection (naive, seasonal, trend+seasonal, Fourier) with prediction band")
    def op_forecast(self, data: ForecastInput, ctx: ExecutionContext) -> OpResult:
        y = np.asarray(data.values, dtype=float)
        if np.isnan(y).any():
            raise EngineError("MISSING_VALUES", "Series contains NaN; clean it first (data.clean)")
        n, m = len(y), data.season_length
        h = min(data.holdout or data.horizon, max(1, n // 4))

        def candidates(length: int) -> dict[str, Any]:
            out: dict[str, Any] = {"last_value": _f_last, "linear_trend": _f_trend_seasonal_factory(None)}
            if m and length >= m:
                out["seasonal_naive"] = _f_seasonal_naive
                out["fourier_ridge"] = _f_fourier
            if m and length >= 2 * m:
                out["seasonal_mean"] = _f_seasonal_mean
                out["trend_seasonal_ridge"] = _f_trend_seasonal_factory(m)
            return out

        baseline_name = "seasonal_naive" if m and n - h >= m else "last_value"
        scores: dict[str, float] = {}
        if n - 2 * h >= max(8, m or 0):
            # Select on a validation window, then report on a later, untouched test window.
            train1, val = y[: n - 2 * h], y[n - 2 * h: n - h]
            for name, fn in candidates(len(train1)).items():
                scores[name] = round(float(mean_absolute_error(val, fn(train1, h, m))), 4)
            selected = min(scores, key=scores.get)
            selection = "lowest MAE on validation window preceding the test window"
        else:
            selected = "trend_seasonal_ridge" if m and n - h >= 2 * m else "linear_trend"
            selection = "series too short for validation; default model"
        fns = candidates(n - h)
        fn = fns.get(selected) or fns["linear_trend"]
        train2, actual = y[: n - h], y[n - h:]
        pred = fn(train2, h, m)
        base = fns[baseline_name](train2, h, m)
        model_mae, base_mae = float(mean_absolute_error(actual, pred)), float(mean_absolute_error(actual, base))
        nz = actual != 0
        mape = float(np.mean(np.abs((actual[nz] - pred[nz]) / actual[nz])) * 100) if nz.any() else None
        sigma = float(np.std(actual - pred, ddof=1)) if h > 1 else float(abs(actual - pred).mean())

        forecast = (candidates(n).get(selected) or fns["linear_trend"])(y, data.horizon, m)
        return OpResult(result={
            "forecast": [round(float(v), 4) for v in forecast],
            "lower": [round(float(v - 1.96 * sigma), 4) for v in forecast],
            "upper": [round(float(v + 1.96 * sigma), 4) for v in forecast],
            "selected_model": selected, "validation_mae": scores,
            "backtest": {"holdout_points": h, "model": selected, "model_mae": round(model_mae, 4), "baseline": baseline_name.replace("_", " "),
                         "baseline_mae": round(base_mae, 4), "model_mape_pct": round(mape, 2) if mape is not None else None,
                         "beats_baseline": model_mae < base_mae,
                         "actual": [round(float(v), 4) for v in actual], "predicted": [round(float(v), 4) for v in pred]},
            "history_points": n, "horizon": data.horizon, "season_length": m,
        }, metadata={"method": "model selection over naive/seasonal/ridge forecasters", "selection": selection,
                     "interval_note": "approximate 95% band from out-of-sample backtest error std; assumes stable error"})

    # ---------------------------------------------------------------- text
    @operation("text_classify", TextClassifyInput, description="TF-IDF + logistic regression text classifier with cross-validated metrics")
    def op_text_classify(self, data: TextClassifyInput, ctx: ExecutionContext) -> OpResult:
        labels = pd.Series(data.labels).astype(str)
        counts = labels.value_counts()
        if len(counts) < 2:
            raise EngineError("ONE_CLASS", "Need at least two label classes")

        def build():
            return make_pipeline(TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True),
                                 LogisticRegression(max_iter=2000))

        folds = int(min(5, counts.min()))
        warnings: list[str] = []
        metrics = None
        if folds >= 2:
            cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=data.random_state)
            cv_pred = cross_val_predict(build(), data.texts, labels, cv=cv,
                                        params={"logisticregression__sample_weight": compute_sample_weight("balanced", np.asarray(labels, dtype=object))})
            metrics = _clf_metrics(labels, cv_pred, sorted(counts.index))
            metrics["cv_folds"] = folds
            metrics["baseline_majority_accuracy"] = round(float(counts.max() / counts.sum()), 4)
        else:
            warnings.append("Some classes have a single example; cross-validation skipped, no metrics reported")
        if len(data.texts) < 50:
            warnings.append(f"Only {len(data.texts)} training texts: metrics have high variance")
        model = build()
        _fit_balanced(model, data.texts, labels)
        vec, clf = model[0], model[-1]
        vocab = np.array(vec.get_feature_names_out())
        coefs = np.atleast_2d(clf.coef_)
        top_terms = {}
        for i, cls in enumerate(clf.classes_):
            row = coefs[i] if coefs.shape[0] > 1 else (coefs[0] if i == 1 else -coefs[0])
            top_terms[str(cls)] = vocab[np.argsort(row)[::-1][:8]].tolist()
        model_id = self._keep({"task": "text_classification", "model": model})
        result: dict[str, Any] = {"model_id": model_id, "metrics": metrics, "top_terms": top_terms,
                                  "class_counts": {k: int(v) for k, v in counts.items()}}
        confidence = None
        if data.predict:
            proba = model.predict_proba(data.predict)
            classes = [str(c) for c in clf.classes_]
            preds = []
            for text, row in zip(data.predict, proba):
                i = int(np.argmax(row))
                preds.append({"text": text[:200], "label": classes[i], "probability": round(float(row[i]), 4)})
            result["predictions"] = preds
            confidence = round(float(np.mean([p["probability"] for p in preds])), 4)
        return OpResult(result=result, confidence=confidence, warnings=warnings,
                        metadata={"confidence_basis": "mean uncalibrated max class probability" if confidence is not None else None})

    @operation("evaluate", EvaluateInput, description="Compute classification or regression metrics from predictions")
    def op_evaluate(self, data: EvaluateInput, ctx: ExecutionContext) -> OpResult:
        if len(data.y_true) != len(data.y_pred):
            raise EngineError("LENGTH_MISMATCH", "y_true and y_pred must have equal length")
        if data.task == "classification":
            yt, yp = [str(v) for v in data.y_true], [str(v) for v in data.y_pred]
            return OpResult(result=_clf_metrics(yt, yp, sorted(set(yt) | set(yp))))
        try:
            yt, yp = np.asarray(data.y_true, float), np.asarray(data.y_pred, float)
        except (TypeError, ValueError) as exc:
            raise EngineError("NOT_NUMERIC", "Regression evaluation needs numeric values") from exc
        return OpResult(result=_reg_metrics(yt, yp))

    @operation("list_models", EmptyInput, description="Models currently held in memory")
    def op_list_models(self, data: EmptyInput, ctx: ExecutionContext) -> OpResult:
        return OpResult(result={"models": [{"model_id": k, "task": v["task"], "created": v["created"]} for k, v in self._models.items()]})


# ---------------------------------------------------------------- forecasters (y_train, horizon, season) -> predictions
def _f_last(y: np.ndarray, h: int, m: int | None) -> np.ndarray:
    return np.full(h, y[-1])


def _f_seasonal_naive(y: np.ndarray, h: int, m: int | None) -> np.ndarray:
    return np.array([y[len(y) - m + (i % m)] for i in range(h)])


def _f_seasonal_mean(y: np.ndarray, h: int, m: int | None) -> np.ndarray:
    k = min(4, len(y) // m)
    profile = y[len(y) - k * m:].reshape(k, m).mean(axis=0)
    return np.array([profile[i % m] for i in range(h)])


def _f_trend_seasonal_factory(m: int | None):
    def fn(y: np.ndarray, h: int, _m: int | None) -> np.ndarray:
        def design(t: np.ndarray) -> np.ndarray:
            cols = [t / len(y)]
            if m:
                cols.append(np.eye(m)[t % m])
            return np.column_stack(cols)
        t = np.arange(len(y))
        model = Ridge(alpha=1.0).fit(design(t), y)
        return model.predict(design(np.arange(len(y), len(y) + h)))
    return fn


def _f_fourier(y: np.ndarray, h: int, m: int | None) -> np.ndarray:
    def design(t: np.ndarray) -> np.ndarray:
        cols = [t / len(y)]
        for k in range(1, min(4, m // 2) + 1):
            cols += [np.sin(2 * np.pi * k * t / m), np.cos(2 * np.pi * k * t / m)]
        return np.column_stack(cols)
    t = np.arange(len(y))
    return Ridge(alpha=1.0).fit(design(t), y).predict(design(np.arange(len(y), len(y) + h)))
