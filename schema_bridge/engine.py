"""Allowlisted deterministic transformations and SQL generation."""
from __future__ import annotations
from datetime import datetime
import re
import pandas as pd
from .models import Rule

def apply_rule(value, rule: Rule):
    if pd.isna(value): return None
    kind, p = rule.type, rule.params
    s = str(value)
    if kind == "COPY": return value
    if kind == "CAST":
        typ=p.get("type","string")
        return float(s) if typ in ("float","number") else int(float(s)) if typ in ("int","integer") else s
    if kind == "TRIM_CASE":
        mode=p.get("mode","upper"); s=s.strip()
        return s.upper() if mode=="upper" else s.lower() if mode=="lower" else s.title()
    if kind == "DATE_PARSE":
        for fmt in p.get("formats",[]):
            try: return datetime.strptime(s.strip(),fmt).date().isoformat()
            except ValueError: continue
        return None
    if kind == "SPLIT":
        parts=s.split(p.get("delimiter",",")); idx=int(p.get("index",0)); return parts[idx].strip() if -len(parts)<=idx<len(parts) else None
    if kind == "CONCAT": return str(p.get("value",s))
    if kind == "LOOKUP": return p.get("map",{}).get(s.strip(),p.get("default"))
    if kind == "DEFAULT": return value if s else p.get("value")
    if kind == "REGEX_EXTRACT":
        m=re.search(p.get("pattern",".*"),s); return m.group(int(p.get("group",0))) if m else None
    if kind == "NUMERIC_SCALE": return float(s.replace(",",""))*float(p.get("factor",1))
    if kind == "CUSTOM": return None
    raise ValueError(f"Unsupported rule: {kind}")

def transform_series(series: pd.Series, rule: Rule) -> pd.Series:
    return series.map(lambda value: apply_rule(value,rule))

def sql_expression(source: str, rule: Rule) -> str:
    col='"'+source.replace('"','""')+'"'; p=rule.params
    if rule.type=="COPY": return col
    if rule.type=="TRIM_CASE": return f"UPPER(TRIM({col}))" if p.get("mode")=="upper" else f"LOWER(TRIM({col}))"
    if rule.type=="NUMERIC_SCALE": return f"CAST({col} AS DECIMAL) * {float(p.get('factor',1))}"
    if rule.type=="CAST": return f"CAST({col} AS {p.get('type','VARCHAR').upper()})"
    if rule.type=="LOOKUP":
        arms=" ".join(f"WHEN '{str(k).replace(chr(39),chr(39)*2)}' THEN '{str(v).replace(chr(39),chr(39)*2)}'" for k,v in p.get("map",{}).items())
        default=p.get("default"); tail=f" ELSE '{default}'" if default is not None else ""
        return f"CASE {col} {arms}{tail} END"
    if rule.type=="DATE_PARSE":
        formats={"%m%d%Y":"MMDDYYYY","%y%m%d":"YYMMDD","%Y-%m-%d":"YYYY-MM-DD","%m/%d/%Y":"MM/DD/YYYY","%m-%d-%Y":"MM-DD-YYYY","%Y%m%d":"YYYYMMDD"}
        attempts=[f"TRY_TO_DATE({col}, '{formats[f]}')" for f in p.get("formats",[]) if f in formats]
        return "COALESCE("+", ".join(attempts)+")" if attempts else f"TRY_TO_DATE({col})"
    if rule.type=="SPLIT": return f"SPLIT_PART({col}, '{p.get('delimiter',',')}', {int(p.get('index',0))+1})"
    if rule.type=="REGEX_EXTRACT": return f"REGEXP_SUBSTR({col}, '{str(p.get('pattern','')).replace(chr(39),chr(39)*2)}')"
    if rule.type=="CONCAT": return f"CONCAT({col}, '{str(p.get('separator','')).replace(chr(39),chr(39)*2)}')"
    if rule.type=="DEFAULT": return f"COALESCE({col}, '{p.get('value','')}')"
    return f"/* review required: {rule.type} */ {col}"
