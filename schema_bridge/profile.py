"""Data-aware profiling for CSV columns."""
from __future__ import annotations
import re
import pandas as pd

def profile_column(series: pd.Series) -> dict:
    values = series.dropna().astype(str)
    sample = values.head(8).tolist()
    distinct = values.unique().tolist()
    patterns: list[str] = []
    if any(re.search(r"\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|^\d{6,8}$", v) for v in sample): patterns.append("date_like")
    if any(re.fullmatch(r"[-+]?\d+(\.\d+)?", v.replace(",", "")) for v in sample): patterns.append("numeric_like")
    if any(re.search(r"\+?\d[\d ()-]{7,}", v) for v in sample): patterns.append("phone_like")
    if len(distinct) <= min(30, max(1, len(values) * .6)): patterns.append("code_like")
    if any("," in v for v in sample): patterns.append("delimited_text")
    dtype = str(series.dtype)
    inferred = "numeric" if pd.api.types.is_numeric_dtype(series) else "date" if "date_like" in patterns else "string"
    return {"name": str(series.name), "type": inferred, "dtype": dtype,
            "null_rate": float(series.isna().mean()), "patterns": patterns,
            "min": str(values.min()) if inferred == "numeric" and len(values) else None,
            "max": str(values.max()) if inferred == "numeric" and len(values) else None,
            "distinct": distinct[:30], "samples": sample}

def profile_frame(frame: pd.DataFrame) -> list[dict]:
    return [profile_column(frame[c]) for c in frame.columns]

