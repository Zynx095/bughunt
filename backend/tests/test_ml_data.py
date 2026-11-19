import math

import numpy as np


def _blobs(n=150, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        c = i % 3
        rows.append({"x": float(rng.normal(c * 5, 0.6)), "y": float(rng.normal(c * -4, 0.6)),
                     "color": ["red", "green", "blue"][c], "label": f"c{c}"})
    return rows


def test_classify_beats_baseline_and_predicts(run):
    rows = _blobs()
    r = run("ml", "classify", {"records": rows, "target": "label", "features": ["x", "y", "color"],
                               "predict": [{"x": 0.1, "y": 0.0, "color": "red"}, {"x": 10, "y": -8, "color": "blue"}]})
    assert r.success, r.error
    m = r.result["metrics"]
    assert m["accuracy"] > m["baseline_majority_accuracy"]
    assert [p["label"] for p in r.result["predictions"]] == ["c0", "c2"]
    assert 0 < r.confidence <= 1
    again = run("ml", "predict", {"model_id": r.result["model_id"], "records": [{"x": 5, "y": -4, "color": "green"}]})
    assert again.result["predictions"][0]["label"] == "c1"


def test_classify_reports_auc_for_binary(run):
    rng = np.random.default_rng(1)
    rows = [{"a": float(v), "t": int(v > 0)} for v in rng.normal(0, 1, 120)]
    r = run("ml", "classify", {"records": rows, "target": "t", "model": "logistic_regression"})
    assert r.success and r.result["metrics"]["roc_auc"] > 0.9


def test_regress(run):
    rows = [{"x": float(i), "y": 3 * i + 2} for i in range(60)]
    r = run("ml", "regress", {"records": rows, "target": "y", "model": "linear"})
    assert r.result["metrics"]["r2"] > 0.99
    assert r.result["metrics"]["mae"] < r.result["metrics"]["baseline_mean_mae"]


def test_cluster_finds_three_groups(run):
    r = run("ml", "cluster", {"records": _blobs(), "features": ["x", "y"]})
    assert r.result["k"] == 3 and r.result["silhouette"] > 0.7
    assert len(r.result["projection"]) == 150


def test_anomaly_flags_injected_outlier(run):
    rng = np.random.default_rng(2)
    rows = [{"id": i, "a": float(rng.normal(10, 1)), "b": float(rng.normal(5, 0.5))} for i in range(100)]
    rows.append({"id": 999, "a": 40.0, "b": -10.0})
    r = run("ml", "anomaly", {"records": rows, "id_field": "id", "contamination": 0.02})
    flagged = {row["id"] for row in r.result["rows"] if row["is_anomaly"]}
    assert 999 in flagged
    outlier = next(row for row in r.result["rows"] if row["id"] == 999)
    assert outlier["anomaly_score"] == max(row["anomaly_score"] for row in r.result["rows"])
    assert {d["feature"] for d in outlier["top_deviations"]} == {"a", "b"}
    assert r.confidence is None


def test_forecast_seasonal_beats_naive_baseline(run):
    vals = [50 + 20 * math.sin(2 * math.pi * t / 24) + 0.5 * t / 24 for t in range(24 * 10)]
    r = run("ml", "forecast", {"values": vals, "horizon": 24, "season_length": 24})
    assert r.success
    bt = r.result["backtest"]
    assert len(r.result["forecast"]) == 24
    assert bt["model_mae"] <= bt["baseline_mae"]
    assert all(lo <= f <= hi for lo, f, hi in zip(r.result["lower"], r.result["forecast"], r.result["upper"]))


def test_forecast_rejects_nan(run):
    r = run("ml", "forecast", {"values": [1, 2, 3, 4, 5, 6, 7, float("nan")]})
    assert not r.success


def test_text_classify(run):
    texts = ["fire smoke flames", "smoke and fire in kitchen", "flames on roof", "burning smell smoke",
             "man not breathing", "chest pain collapsed", "unconscious woman", "seizure child breathing"]
    labels = ["fire"] * 4 + ["medical"] * 4
    r = run("ml", "text_classify", {"texts": texts, "labels": labels, "predict": ["heavy smoke and flames", "he collapsed, not breathing"]})
    assert r.success and [p["label"] for p in r.result["predictions"]] == ["fire", "medical"]
    assert r.result["metrics"]["cv_folds"] == 4


def test_evaluate(run):
    r = run("ml", "evaluate", {"task": "classification", "y_true": [1, 0, 1, 1], "y_pred": [1, 0, 0, 1]})
    assert r.result["accuracy"] == 0.75
    r = run("ml", "evaluate", {"task": "regression", "y_true": [1, 2, 3], "y_pred": [1, 2, 4]})
    assert abs(r.result["mae"] - 1 / 3) < 1e-3


# ---------------------------------------------------------------- data engine
CSV = "id,amount,city, note \n1,10.5,Paris, hi \n2,,Paris,ok\n2,,Paris,ok\n3,99,Rome,\n"


def test_ingest_profile_clean(run):
    ing = run("data", "ingest", {"name": "t", "format": "csv", "content": CSV})
    assert ing.success and ing.result["row_count"] == 4
    ds = ing.result["dataset_id"]
    prof = run("data", "profile", {"dataset_id": ds}).result
    amount = next(c for c in prof["columns"] if c["column"] == "amount")
    assert amount["missing"] == 2 and amount["type"] == "number"
    clean = run("data", "clean", {"dataset_id": ds, "fill_missing": "median", "standardise_column_names": True}).result
    assert clean["report"]["duplicates_removed"] == 1
    assert clean["report"]["missing_values_after"] == 0
    assert "note" in clean["records"][0]


def test_ingest_json_and_bad_input(run):
    ok = run("data", "ingest", {"name": "j", "format": "json", "content": '{"rows": [{"a": 1}, {"a": 2}]}'})
    assert ok.result["row_count"] == 2
    bad = run("data", "ingest", {"name": "j", "format": "json", "content": '"just a string"'})
    assert not bad.success and bad.error.code == "INVALID_JSON_SHAPE"


def test_normalise(run):
    r = run("data", "normalise", {"records": [{"a": 0}, {"a": 5}, {"a": 10}], "method": "minmax"}).result
    assert [x["a"] for x in r["records"]] == [0.0, 0.5, 1.0]


def test_text_features_and_entities(run):
    hard = run("data", "text_features", {"text": "Notwithstanding the aforementioned considerations, institutional "
                                                  "administrators must comprehensively reevaluate organisational responsibilities."}).result
    easy = run("data", "text_features", {"text": "The cat sat on the mat. It was warm. We had tea."}).result
    assert hard["flesch_kincaid_grade"] > easy["flesch_kincaid_grade"]
    ents = run("data", "extract_entities", {"text": "Mail bob@example.com from 203.0.113.9 re CVE-2024-3400 "
                                                    "hash 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"}).result["entities"]
    assert ents["email"] == ["bob@example.com"] and ents["ipv4"] == ["203.0.113.9"]
    assert ents["cve"] == ["CVE-2024-3400"] and len(ents["sha256"]) == 1 and "md5" not in ents
