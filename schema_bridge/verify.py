"""Rule execution checks; any failure keeps a mapping in human review."""
from __future__ import annotations
import pandas as pd
from .engine import transform_series
from .models import Rule, VerifierResult

def verify_rule(series: pd.Series, rule: Rule, target: dict, source_type: str) -> VerifierResult:
    issues=[]
    if rule.type=="CUSTOM": issues.append("CUSTOM requires a human-authored implementation; it was not executed.")
    try: out=transform_series(series,rule)
    except Exception as exc:
        return VerifierResult(passed=False,pass_rate=0,issues=[f"Rule execution error: {exc}"],preview=[])
    if len(out)!=len(series): issues.append("Row count changed.")
    nonnull=out.dropna()
    if target.get("required") and out.isna().any(): issues.append("Required target has null or unparsed values.")
    target_type=target.get("type")
    if target_type in ("number","integer") and len(nonnull):
        numeric=pd.to_numeric(nonnull,errors="coerce")
        if numeric.isna().any(): issues.append(f"Output contains values that are not valid {target_type} values.")
        elif target_type=="integer" and ((numeric % 1)!=0).any(): issues.append("Output contains a fractional value for an integer target.")
    elif target_type=="date" and len(nonnull):
        valid=nonnull.map(lambda x: pd.notna(pd.to_datetime(x,errors="coerce")))
        if not valid.all(): issues.append("Output contains values that are not valid dates.")
    elif target_type=="boolean" and len(nonnull):
        allowed_bool={True,False,0,1,"true","false","True","False"}
        if not all(x in allowed_bool for x in nonnull): issues.append("Output contains values that are not valid booleans.")
    if rule.type=="DATE_PARSE" and len(series.dropna()) and len(nonnull)/len(series.dropna())<.98: issues.append("Fewer than 98% of non-null dates parsed.")
    if rule.type=="LOOKUP":
        unmapped=sorted(set(series.dropna().astype(str))-set(map(str,rule.params.get("map",{}))))
        if unmapped: issues.append(f"Unmapped observed codes: {', '.join(unmapped[:8])}")
    allowed=target.get("allowed_values") or []
    bad=set(map(str,nonnull.unique()))-set(map(str,allowed)) if allowed else set()
    if bad and rule.type=="LOOKUP": issues.append(f"Values outside target allowed values: {', '.join(sorted(bad)[:5])}")
    rate=float(len(nonnull)/max(1,len(series.dropna())))
    return VerifierResult(passed=not issues,pass_rate=rate,issues=issues,preview=[{"source":str(a),"target":None if pd.isna(b) else str(b)} for a,b in zip(series.head(8),out.head(8))])
