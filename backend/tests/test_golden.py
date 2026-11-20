"""Golden-data tests: manifest values are re-derived from the CSVs on disk.

If the data ever changes without the manifest being regenerated, these fail.
No number here is hand-typed from memory — expected values come from
golden_manifest.json, which generate_golden.py computed from the files.
"""
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
GOLDEN_DIR = BACKEND_DIR / "data" / "golden"

MANIFEST = json.loads((GOLDEN_DIR / "golden_manifest.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("key", ["clean", "dirty", "corr"])
def test_manifest_matches_file(key):
    info = MANIFEST["datasets"][key]
    path = GOLDEN_DIR / info["file"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == info["sha256"]
    df = pd.read_csv(path)
    assert len(df) == info["rows"]
    assert len(df.columns) == info["cols"]
    assert list(df.columns) == info["columns"]
    assert int(df.isna().sum().sum()) == info["total_missing"]
    assert int(df.duplicated().sum()) == info["duplicate_rows"]
    for col, stats in info["column_stats"].items():
        s = df[col]
        assert int(s.isna().sum()) == stats["missing"]
        if "mean" in stats:  # numeric column
            assert abs(float(s.mean()) - stats["mean"]) < 1e-5
            assert abs(float(s.median()) - stats["median"]) < 1e-5
            assert abs(float(s.std(ddof=1)) - stats["std"]) < 1e-5
            assert abs(float(s.min()) - stats["min"]) < 1e-5
            assert abs(float(s.max()) - stats["max"]) < 1e-5


def test_clean_is_actually_clean():
    info = MANIFEST["datasets"]["clean"]
    assert info["rows"] == 200
    assert info["total_missing"] == 0
    assert info["duplicate_rows"] == 0


def test_dirty_has_known_defects():
    info = MANIFEST["datasets"]["dirty"]
    assert info["rows"] == 126  # 120 + 6 duplicated rows
    assert info["total_missing"] == 16
    assert info["duplicate_rows"] == 6
    assert info["column_stats"]["temperature"]["non_numeric_values"] == 1
    assert info["column_stats"]["humidity"]["non_numeric_values"] == 1
    assert info["column_stats"]["concentration"]["non_numeric_values"] == 1


def test_corr_strong_linear_relation():
    info = MANIFEST["datasets"]["corr"]
    assert info["rows"] == 150
    assert info["pearson_dose_response"] > 0.95
    assert abs(info["pearson_dose_response"] - 0.98506) < 1e-4


def test_ai_adapter_privacy_and_fallback():
    from app.ai_adapter import (
        ColumnSummary,
        DeepSeekProvider,
        GeminiProvider,
        StatsSummary,
        summarize,
    )

    summary = StatsSummary(
        dataset_name="clean.csv",
        rows=200,
        cols=5,
        file_hash="x" * 64,
        columns=(
            ColumnSummary(name="temperature", dtype="float64", count=200, missing=0,
                          mean=24.95465, median=24.925, std=1.322891, minimum=21.8, maximum=29.37),
        ),
        quality_score=100.0,
        findings=(),
    )
    # No raw-row field exists on the summary type (privacy is structural).
    assert not hasattr(summary, "rows_data")
    assert not hasattr(summary, "raw_data")
    text, manifest = summarize(summary)
    # Fallback text is built from the real numbers in the summary.
    assert "24.95" in text and "200" in text
    assert manifest.raw_rows_sent == 0
    assert manifest.model == "rule-based-fallback"
    # Wave 3: Gemini IS wired (via the custom.gemini helper subprocess), so
    # available() is True when the helper file exists; DeepSeek stays a stub.
    # The live Gemini call itself is covered by mocked tests in test_report.py
    # (tests must never call a real model).
    assert GeminiProvider().available() is True
    assert DeepSeekProvider().available() is False
    with pytest.raises(NotImplementedError):
        DeepSeekProvider().summarize(summary)
