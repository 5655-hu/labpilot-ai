#!/usr/bin/env python3
"""Generate the three golden demo datasets and their verified manifest.

All expected values in golden_manifest.json are computed FROM the written
CSV files (read back with pandas), never hand-typed. Tests assert against
these values, so any regeneration that changes the data fails loudly.

Deterministic: every random draw uses a fixed seed, and every injected
defect is placed at a fixed row index.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent.parent / "data" / "golden"
OUT.mkdir(parents=True, exist_ok=True)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def describe(df: pd.DataFrame) -> dict:
    """Expected values computed from the file on disk."""
    cols = {}
    for c in df.columns:
        s = df[c]
        numeric = pd.to_numeric(s, errors="coerce")
        is_num = numeric.notna().sum() > 0 and s.dtype != object or pd.api.types.is_numeric_dtype(s)
        entry = {
            "dtype": str(s.dtype),
            "missing": int(s.isna().sum()),
            "non_null": int(s.notna().sum()),
        }
        if pd.api.types.is_numeric_dtype(s):
            entry.update(
                {
                    "mean": round(float(s.mean()), 6),
                    "median": round(float(s.median()), 6),
                    "std": round(float(s.std(ddof=1)), 6),
                    "min": round(float(s.min()), 6),
                    "max": round(float(s.max()), 6),
                }
            )
        else:
            # object column: count values that fail numeric coercion (type errors)
            entry["non_numeric_values"] = int((numeric.isna() & s.notna()).sum())
        cols[c] = entry
    return {
        "rows": int(len(df)),
        "cols": int(len(df.columns)),
        "columns": list(df.columns),
        "duplicate_rows": int(df.duplicated().sum()),
        "total_missing": int(df.isna().sum().sum()),
        "column_stats": cols,
    }


def write(df: pd.DataFrame, name: str) -> dict:
    path = OUT / name
    df.to_csv(path, index=False)
    info = describe(pd.read_csv(path))
    info["file"] = name
    info["sha256"] = sha256(path)
    return info


def main() -> None:
    rng = np.random.default_rng(42)

    # ---- clean: 200 rows, no missing / duplicates / type errors / outliers ----
    n = 200
    clean = pd.DataFrame(
        {
            "sample_id": np.arange(1, n + 1),
            "temperature": np.round(np.clip(rng.normal(25.0, 1.5, n), 20.0, 30.0), 2),
            "humidity": np.round(np.clip(rng.normal(55.0, 5.0, n), 40.0, 70.0), 2),
            "pressure": np.round(np.clip(rng.normal(101.3, 0.8, n), 99.0, 103.5), 2),
            "reaction_time": np.round(np.clip(rng.normal(12.0, 2.0, n), 6.0, 18.0), 2),
        }
    )
    clean_info = write(clean, "clean.csv")

    # ---- dirty: 120 rows with injected defects at fixed indices ----
    n = 120
    dirty = pd.DataFrame(
        {
            "sample_id": np.arange(1, n + 1),
            "temperature": np.round(np.clip(rng.normal(25.0, 1.5, n), 20.0, 30.0), 2),
            "humidity": np.round(np.clip(rng.normal(55.0, 5.0, n), 40.0, 70.0), 2),
            "concentration": np.round(np.clip(rng.normal(0.50, 0.08, n), 0.30, 0.70), 3),
        }
    )
    # missing values (exact positions recorded in the manifest notes)
    for idx in [5, 17, 42, 63, 88, 101, 110, 115]:
        dirty.loc[idx, "temperature"] = np.nan
    for idx in [9, 33, 77, 95, 108]:
        dirty.loc[idx, "humidity"] = np.nan
    for idx in [21, 58]:
        dirty.loc[idx, "concentration"] = np.nan
    # outliers (real values, flagged "to confirm", never deleted)
    dirty.loc[3, "temperature"] = 48.6
    dirty.loc[71, "temperature"] = -4.2
    dirty.loc[50, "concentration"] = 2.450
    # type errors: unit text / placeholder text inside numeric columns
    # (cast to object first so the assignment is explicit, not a pandas warning)
    for col in ("temperature", "humidity", "concentration"):
        dirty[col] = dirty[col].astype(object)
    dirty.loc[12, "temperature"] = "25.3C"
    dirty.loc[44, "temperature"] = "N/A"
    dirty.loc[66, "humidity"] = "high"
    dirty.loc[90, "concentration"] = "0.52 mol/L"
    # duplicate rows: copy rows 10, 25, 40, 55, 80, 99 exactly (appended at end)
    dup_idx = [10, 25, 40, 55, 80, 99]
    dirty = pd.concat([dirty, dirty.loc[dup_idx]], ignore_index=True)
    dirty_info = write(dirty, "dirty.csv")
    dirty_info["injected"] = {
        "readback_note": "temperature row 44 'N/A' is parsed as NaN by pandas on read-back, so it counts as missing (9) not as a type error; remaining type errors are '25.3C' (temperature), 'high' (humidity), '0.52 mol/L' (concentration). Manifest values are read-back values.",
        "missing_temperature_rows": [5, 17, 42, 63, 88, 101, 110, 115],
        "missing_humidity_rows": [9, 33, 77, 95, 108],
        "missing_concentration_rows": [21, 58],
        "outlier_rows": {"temperature": [3, 71], "concentration": [50]},
        "type_error_rows": {"temperature": [12, 44], "humidity": [66], "concentration": [90]},
        "duplicated_source_rows": dup_idx,
    }

    # ---- corr: 150 rows, strong dose -> response linear relation ----
    n = 150
    dose = np.round(np.linspace(0.1, 5.0, n) + rng.normal(0, 0.05, n), 3)
    response = np.round(2.5 * dose + 1.2 + rng.normal(0, 0.6, n), 3)
    corr = pd.DataFrame(
        {
            "sample_id": np.arange(1, n + 1),
            "dose": dose,
            "response": response,
            "temperature": np.round(np.clip(rng.normal(24.0, 1.0, n), 21.0, 27.0), 2),
            "group": ["control"] * 75 + ["treatment"] * 75,
        }
    )
    corr_info = write(corr, "corr.csv")
    df = pd.read_csv(OUT / "corr.csv")
    corr_info["pearson_dose_response"] = round(
        float(df["dose"].corr(df["response"], method="pearson")), 6
    )

    manifest = {
        "version": 1,
        "generated_by": "backend/scripts/generate_golden.py (seed 42, defects at fixed indices)",
        "note": "All expected values are computed from the written CSV files, not hand-typed.",
        "datasets": {
            "clean": clean_info,
            "dirty": dirty_info,
            "corr": corr_info,
        },
    }
    (OUT / "golden_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
