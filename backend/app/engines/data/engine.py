"""Data engine: ingestion (CSV/JSON/PDF/images), profiling, cleaning,
normalisation, feature and entity extraction."""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, model_validator

from app.core.contracts import EngineError, ExecutionContext, OpResult
from app.core.engine import BaseEngine, operation
from app.engines.common import MAX_ROWS, RecordsInput, frame_records, load_frame, to_jsonable

from app.engines.text import ENTITY_PATTERNS, extract_entities, readability


class IngestInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    format: Literal["csv", "json"] | None = Field(None, description="Required with inline content; inferred for documents")
    content: str | None = Field(None, max_length=50_000_000, description="Inline CSV or JSON text")
    document_id: str | None = Field(None, description="Uploaded CSV/JSON document")

    @model_validator(mode="after")
    def _one_source(self):
        if (self.content is None) == (self.document_id is None):
            raise ValueError("Provide exactly one of 'content' or 'document_id'")
        if self.content is not None and self.format is None:
            raise ValueError("'format' is required with inline content")
        return self


class CleanInput(RecordsInput):
    drop_duplicates: bool = True
    trim_strings: bool = True
    standardise_column_names: bool = False
    fill_missing: Literal["none", "median", "mean", "mode", "drop_rows"] = "median"
    drop_columns: list[str] = Field(default_factory=list)


class NormaliseInput(RecordsInput):
    columns: list[str] | None = None
    method: Literal["zscore", "minmax"] = "zscore"


class FeatureInput(RecordsInput):
    datetime_columns: list[str] = Field(default_factory=list)
    text_columns: list[str] = Field(default_factory=list)


class TextInput(BaseModel):
    text: str = Field(..., min_length=1, max_length=2_000_000)


class EntityInput(TextInput):
    types: list[str] | None = Field(None, description=f"Subset of: {', '.join(ENTITY_PATTERNS)}")


class DocumentInput(BaseModel):
    document_id: str
    max_chars: int = Field(200_000, ge=100, le=2_000_000)


class ImageInput(BaseModel):
    document_id: str


class EmptyInput(BaseModel):
    pass


def _infer_type(series: pd.Series) -> str:
    s = series.dropna()
    if s.empty:
        return "empty"
    if pd.api.types.is_bool_dtype(s):
        return "boolean"
    if pd.api.types.is_numeric_dtype(s):
        return "integer" if pd.api.types.is_integer_dtype(s) else "number"
    if s.astype(str).str.match(r"^\d{4}-\d{2}-\d{2}").mean() > 0.9:
        return "datetime"
    return "categorical" if s.nunique() <= max(20, len(s) * 0.05) else "text"


def _profile(df: pd.DataFrame) -> list[dict[str, Any]]:
    cols = []
    for c in df.columns:
        s = df[c]
        info: dict[str, Any] = {"column": str(c), "type": _infer_type(s), "missing": int(s.isna().sum()),
                                "unique": int(s.nunique(dropna=True))}
        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            d = s.describe()
            info.update({k: to_jsonable(d.get(k)) for k in ("mean", "std", "min", "max")})
            info["median"] = to_jsonable(s.median())
        else:
            top = s.dropna().astype(str).value_counts().head(5)
            info["top_values"] = [{"value": k, "count": int(v)} for k, v in top.items()]
        cols.append(info)
    return cols


class DataEngine(BaseEngine):
    name = "data"
    title = "Data Engine"
    description = "CSV/JSON/PDF/image ingestion, profiling, cleaning, normalisation and feature/entity extraction."

    def __init__(self, store=None) -> None:
        super().__init__()
        self.store = store

    def _doc(self, doc_id: str) -> tuple[dict, Path]:
        if self.store is None:
            raise EngineError("NO_STORE", "Document storage is not configured", 503)
        doc = self.store.get_document(doc_id)
        if doc is None:
            raise EngineError("DOCUMENT_NOT_FOUND", f"Unknown document '{doc_id}'", 404)
        path = Path(doc["storage_path"])
        if not path.exists():
            raise EngineError("FILE_MISSING", "Stored file is missing", 410)
        return doc, path

    @operation("ingest", IngestInput, access="write", description="Parse CSV/JSON into a stored dataset with an inferred schema")
    def op_ingest(self, data: IngestInput, ctx: ExecutionContext) -> OpResult:
        fmt, text, source, doc_id = data.format, data.content, "inline", None
        if data.document_id:
            doc, path = self._doc(data.document_id)
            if doc["kind"] not in ("csv", "json"):
                raise EngineError("UNSUPPORTED_DOCUMENT", f"Document kind '{doc['kind']}' cannot be ingested as a table")
            fmt, text, source, doc_id = doc["kind"], path.read_text(encoding="utf-8-sig", errors="replace"), "document", doc["id"]
        try:
            if fmt == "csv":
                df = pd.read_csv(io.StringIO(text or ""), nrows=MAX_ROWS + 1)
            else:
                parsed = json.loads(text or "null")
                if isinstance(parsed, dict):
                    parsed = next((v for v in parsed.values() if isinstance(v, list)), [parsed])
                if not isinstance(parsed, list) or not all(isinstance(r, dict) for r in parsed):
                    raise EngineError("INVALID_JSON_SHAPE", "JSON must be a list of objects (or an object containing one)")
                df = pd.json_normalize(parsed, max_level=1)
        except (pd.errors.ParserError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise EngineError("PARSE_ERROR", f"Could not parse {fmt}: {exc}") from exc
        if df.empty:
            raise EngineError("EMPTY_DATASET", "No rows found")
        warnings = []
        if len(df) > MAX_ROWS:
            df = df.head(MAX_ROWS)
            warnings.append(f"Truncated to {MAX_ROWS} rows")
        df.columns = [str(c).strip() for c in df.columns]
        records = frame_records(df)
        profile = _profile(df)
        if self.store is None:
            raise EngineError("NO_STORE", "Dataset storage is not configured", 503)
        ds = self.store.add_dataset(name=data.name, source=source, document_id=doc_id,
                                    columns=profile, row_count=len(records), records=records)
        self.store.audit("data", "dataset_ingested", actor=ctx.actor, role=ctx.role,
                         detail={"dataset_id": ds["id"], "rows": len(records), "source": source})
        return OpResult(result={"dataset_id": ds["id"], "name": data.name, "row_count": len(records),
                                "columns": profile, "preview": records[:10]}, warnings=warnings)

    @operation("list_datasets", EmptyInput, description="List stored datasets (metadata only)")
    def op_list_datasets(self, data: EmptyInput, ctx: ExecutionContext) -> OpResult:
        if self.store is None:
            raise EngineError("NO_STORE", "Dataset storage is not configured", 503)
        return OpResult(result={"datasets": self.store.list_datasets()})

    @operation("profile", RecordsInput, description="Per-column types, missing values and summary statistics")
    def op_profile(self, data: RecordsInput, ctx: ExecutionContext) -> OpResult:
        df = load_frame(data, self.store)
        return OpResult(result={"rows": len(df), "columns": _profile(df),
                                "duplicate_rows": int(df.astype(str).duplicated().sum())})

    @operation("clean", CleanInput, description="Deduplicate, trim, drop columns and impute missing values")
    def op_clean(self, data: CleanInput, ctx: ExecutionContext) -> OpResult:
        df = load_frame(data, self.store)
        report: dict[str, Any] = {"rows_in": len(df)}
        if data.standardise_column_names:
            df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
        if data.drop_columns:
            df = df.drop(columns=[c for c in data.drop_columns if c in df.columns])
        if data.trim_strings:
            for c in df.select_dtypes(include="object").columns:
                df[c] = df[c].map(lambda v: v.strip() if isinstance(v, str) else v).replace("", np.nan)
        if data.drop_duplicates:
            before = len(df)
            df = df[~df.astype(str).duplicated()]
            report["duplicates_removed"] = before - len(df)
        missing_before = int(df.isna().sum().sum())
        filled: dict[str, Any] = {}
        if data.fill_missing == "drop_rows":
            df = df.dropna()
        elif data.fill_missing != "none":
            for c in df.columns:
                if not df[c].isna().any():
                    continue
                if pd.api.types.is_numeric_dtype(df[c]) and data.fill_missing in ("median", "mean"):
                    val = df[c].median() if data.fill_missing == "median" else df[c].mean()
                else:
                    mode = df[c].mode(dropna=True)
                    val = mode.iloc[0] if not mode.empty else None
                if val is not None:
                    df[c] = df[c].fillna(val)
                    filled[c] = to_jsonable(val)
        report.update({"missing_values_before": missing_before, "missing_values_after": int(df.isna().sum().sum()),
                       "filled_with": filled, "rows_out": len(df)})
        return OpResult(result={"records": frame_records(df), "report": report})

    @operation("normalise", NormaliseInput, description="Z-score or min-max scale numeric columns")
    def op_normalise(self, data: NormaliseInput, ctx: ExecutionContext) -> OpResult:
        df = load_frame(data, self.store)
        cols = data.columns or [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])]
        params = {}
        for c in cols:
            if c not in df.columns or not pd.api.types.is_numeric_dtype(df[c]):
                raise EngineError("NOT_NUMERIC", f"Column '{c}' is missing or not numeric")
            s = df[c].astype(float)
            if data.method == "zscore":
                mu, sd = s.mean(), s.std(ddof=0) or 1.0
                df[c] = (s - mu) / sd
                params[c] = {"mean": to_jsonable(mu), "std": to_jsonable(sd)}
            else:
                lo, hi = s.min(), s.max()
                df[c] = (s - lo) / ((hi - lo) or 1.0)
                params[c] = {"min": to_jsonable(lo), "max": to_jsonable(hi)}
        return OpResult(result={"records": frame_records(df), "method": data.method, "parameters": params})

    @operation("extract_features", FeatureInput, description="Derive date-part and text-shape features for ML")
    def op_extract_features(self, data: FeatureInput, ctx: ExecutionContext) -> OpResult:
        df = load_frame(data, self.store)
        added: list[str] = []
        for c in data.datetime_columns:
            if c not in df.columns:
                raise EngineError("UNKNOWN_COLUMNS", f"Column '{c}' not found")
            dt = pd.to_datetime(df[c], errors="coerce", utc=True)
            for part in ("hour", "dayofweek", "month"):
                df[f"{c}_{part}"] = getattr(dt.dt, part)
                added.append(f"{c}_{part}")
            df[f"{c}_is_weekend"] = (dt.dt.dayofweek >= 5).astype(int)
            added.append(f"{c}_is_weekend")
        for c in data.text_columns:
            if c not in df.columns:
                raise EngineError("UNKNOWN_COLUMNS", f"Column '{c}' not found")
            s = df[c].fillna("").astype(str)
            df[f"{c}_length"] = s.str.len()
            df[f"{c}_words"] = s.str.split().str.len()
            df[f"{c}_digit_ratio"] = s.map(lambda t: sum(ch.isdigit() for ch in t) / max(1, len(t)))
            df[f"{c}_upper_ratio"] = s.map(lambda t: sum(ch.isupper() for ch in t) / max(1, len(t)))
            added += [f"{c}_length", f"{c}_words", f"{c}_digit_ratio", f"{c}_upper_ratio"]
        return OpResult(result={"records": frame_records(df), "added_features": added})

    @operation("text_features", TextInput, description="Readability metrics (Flesch, Flesch-Kincaid grade) and text statistics")
    def op_text_features(self, data: TextInput, ctx: ExecutionContext) -> OpResult:
        return OpResult(result=readability(data.text), metadata={"method": "Flesch formulas with heuristic syllable counting"})

    @operation("extract_entities", EntityInput, description="Regex extraction of emails, URLs, IPs, hashes, CVEs, phones, dates, money")
    def op_extract_entities(self, data: EntityInput, ctx: ExecutionContext) -> OpResult:
        ents = extract_entities(data.text, data.types)
        return OpResult(result={"entities": ents, "counts": {k: len(v) for k, v in ents.items()}},
                        metadata={"method": "deterministic regular expressions"})

    @operation("document_text", DocumentInput, description="Extract text from an uploaded PDF or text document")
    def op_document_text(self, data: DocumentInput, ctx: ExecutionContext) -> OpResult:
        doc, path = self._doc(data.document_id)
        warnings: list[str] = []
        pages: list[str] = []
        if doc["kind"] == "pdf":
            from pypdf import PdfReader

            try:
                reader = PdfReader(str(path))
                if reader.is_encrypted:
                    raise EngineError("PDF_ENCRYPTED", "Encrypted PDFs are not supported")
                for i, page in enumerate(reader.pages):
                    if i >= 500:
                        warnings.append("Stopped after 500 pages")
                        break
                    pages.append(page.extract_text() or "")
            except EngineError:
                raise
            except Exception as exc:  # noqa: BLE001 - malformed PDFs raise many types
                raise EngineError("PDF_PARSE_ERROR", f"Could not read PDF: {exc}") from exc
            if not any(p.strip() for p in pages):
                warnings.append("No extractable text (scanned PDF?). OCR is not part of the foundation build.")
        elif doc["kind"] in ("txt", "csv", "json"):
            pages = [path.read_text(encoding="utf-8", errors="replace")]
        else:
            raise EngineError("UNSUPPORTED_DOCUMENT", f"Cannot extract text from '{doc['kind']}' documents")
        text = "\n\n".join(pages)
        if len(text) > data.max_chars:
            text = text[: data.max_chars]
            warnings.append(f"Text truncated to {data.max_chars} characters")
        return OpResult(result={"document_id": doc["id"], "filename": doc["filename"], "pages": len(pages),
                                "text": text, "characters": len(text)}, warnings=warnings)

    @operation("image_features", ImageInput, description="Image dimensions, colour/brightness, sharpness, perceptual hashes and EXIF metadata")
    def op_image_features(self, data: ImageInput, ctx: ExecutionContext) -> OpResult:
        from PIL import ExifTags, Image

        doc, path = self._doc(data.document_id)
        if doc["kind"] != "image":
            raise EngineError("UNSUPPORTED_DOCUMENT", "Document is not an image")
        Image.MAX_IMAGE_PIXELS = 80_000_000
        with Image.open(path) as img:
            fmt, mode, size = img.format, img.mode, img.size
            exif = img.getexif()
            exif_tags = {ExifTags.TAGS.get(k, str(k)): str(v)[:120] for k, v in exif.items() if k != 34853}
            try:
                exif_tags.update({ExifTags.TAGS.get(k, str(k)): str(v)[:120]
                                  for k, v in exif.get_ifd(0x8769).items() if not isinstance(v, bytes)})
            except Exception:  # noqa: BLE001 - malformed EXIF is common
                pass
            has_gps = 34853 in exif
            rgb = img.convert("RGB")
            rgb.thumbnail((512, 512))
            arr = np.asarray(rgb, dtype=float)
            gray = np.asarray(img.convert("L").resize((9, 8)), dtype=float)
            small = np.asarray(img.convert("L").resize((8, 8)), dtype=float)
        lum = arr @ np.array([0.299, 0.587, 0.114])
        lap = lum[1:-1, 1:-1] * -4 + lum[:-2, 1:-1] + lum[2:, 1:-1] + lum[1:-1, :-2] + lum[1:-1, 2:]
        ahash = "".join("1" if v > small.mean() else "0" for v in small.flatten())
        dhash = "".join("1" if gray[r, c] > gray[r, c + 1] else "0" for r in range(8) for c in range(8))
        keep = ("Make", "Model", "Software", "DateTime", "DateTimeOriginal", "Artist", "LensModel")
        return OpResult(result={
            "document_id": doc["id"], "format": fmt, "mode": mode, "width": size[0], "height": size[1],
            "mean_rgb": [round(float(x), 1) for x in arr.reshape(-1, 3).mean(axis=0)],
            "brightness": round(float(lum.mean()), 2),
            "sharpness_laplacian_var": round(float(lap.var()), 2) if lap.size else None,
            "average_hash": f"{int(ahash, 2):016x}", "difference_hash": f"{int(dhash, 2):016x}",
            "exif": {k: v for k, v in exif_tags.items() if k in keep}, "exif_tag_count": len(exif_tags),
            "has_gps_metadata": has_gps,
        })
