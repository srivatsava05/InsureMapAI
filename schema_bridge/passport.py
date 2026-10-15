"""Content-addressed evidence passports for reviewable mapping proposals."""
from __future__ import annotations
import hashlib
import json
import pandas as pd


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def evidence_passport(frame: pd.DataFrame, targets: list[dict], dictionary: str, item: dict) -> dict:
    """Build stable input fingerprints and evidence lineage for one proposed mapping."""
    source_hash = _digest(frame.to_csv(index=False).encode("utf-8"))
    target_hash = _digest(json.dumps(targets, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    dictionary_hash = _digest(dictionary.encode("utf-8"))
    source_name = item["source_field"]
    decision = item["decision"]
    payload = {
        "source_hash": source_hash,
        "target_schema_hash": target_hash,
        "dictionary_hash": dictionary_hash,
        "source_field": source_name,
        "target_field": decision.target_field,
        "rule": decision.rule.model_dump(),
    }
    passport_id = _digest(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return {
        "passport_id": passport_id,
        "source_hash": source_hash,
        "target_schema_hash": target_hash,
        "dictionary_hash": dictionary_hash,
        "source_field": source_name,
        "target_field": decision.target_field,
        "profile": item["profile"],
        "candidates": [{"target": c["target"]["name"], "score": c["score"], "dictionary_hits": c.get("dictionary_hits", [])} for c in item["candidates"]],
        "evidence_quote": decision.evidence_quote,
        "rule": decision.rule.model_dump(),
        "verification": {"passed": item["verification"].passed, "pass_rate": item["verification"].pass_rate, "issues": item["verification"].issues},
        "review_status": "pending",
    }


def passport_is_current(passport: dict, frame: pd.DataFrame, targets: list[dict], dictionary: str) -> bool:
    """Return false when any data/schema/dictionary input fingerprint has changed."""
    source_hash = _digest(frame.to_csv(index=False).encode("utf-8"))
    target_hash = _digest(json.dumps(targets, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    dictionary_hash = _digest(dictionary.encode("utf-8"))
    return (passport.get("source_hash") == source_hash and
            passport.get("target_schema_hash") == target_hash and
            passport.get("dictionary_hash") == dictionary_hash)
