"""Helpers shared by engines that operate on tabular records."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, model_validator

from app.core.contracts import EngineError

MAX_ROWS = 100_000


class RecordsInput(BaseModel):
    """Tabular input: inline `records` or a stored `dataset_id`."""

    records: list[dict[str, Any]] | None = Field(None, description="Inline rows (list of objects)")
    dataset_id: str | None = Field(None, description="Id of a dataset created by data.ingest")

    @model_validator(mode="after")
    def _one_source(self):
        if (self.records is None) == (self.dataset_id is None):
            raise ValueError("Provide exactly one of 'records' or 'dataset_id'")
        if self.records is not None and len(self.records) > MAX_ROWS:
            raise ValueError(f"At most {MAX_ROWS} records are supported inline")
        return self


def load_frame(data: RecordsInput, store) -> pd.DataFrame:
    if data.records is not None:
        rows = data.records
    else:
        if store is None:
            raise EngineError("NO_STORE", "Dataset storage is not configured", 503)
        ds = store.get_dataset(data.dataset_id)
        if ds is None:
            raise EngineError("DATASET_NOT_FOUND", f"Unknown dataset '{data.dataset_id}'", 404)
        rows = ds["records"]
    if not rows:
        raise EngineError("EMPTY_DATASET", "No records supplied")
    return pd.DataFrame.from_records(rows)


def to_jsonable(value: Any) -> Any:
    """Convert numpy/pandas scalars and NaN to JSON-safe values."""
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return [to_jsonable(v) for v in value.tolist()]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if math.isnan(f) or math.isinf(f) else round(f, 6)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if value is pd.NaT:
        return None
    return value


def frame_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [to_jsonable(r) for r in df.to_dict(orient="records")]


def numeric_matrix(df: pd.DataFrame, features: list[str] | None, exclude: set[str] | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Select features, one-hot encode categoricals, median-impute numerics."""
    exclude = exclude or set()
    cols = features or [c for c in df.columns if c not in exclude]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise EngineError("UNKNOWN_COLUMNS", f"Columns not found: {missing}", details={"available": list(df.columns)})
    X = df[cols].copy()
    for c in X.columns:
        if X[c].dtype == bool:
            X[c] = X[c].astype(int)
    cat_cols = [c for c in X.columns if not pd.api.types.is_numeric_dtype(X[c])]
    if cat_cols:
        X = pd.get_dummies(X, columns=cat_cols, dummy_na=False, dtype=float)
    X = X.apply(pd.to_numeric, errors="coerce")
    X = X.fillna(X.median(numeric_only=True)).fillna(0.0)
    if X.shape[1] == 0:
        raise EngineError("NO_FEATURES", "No usable feature columns")
    return X.astype(float), list(X.columns)
