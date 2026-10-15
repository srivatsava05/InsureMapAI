"""MongoDB persistence for reviewer decisions, audit events and mapping cache."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from functools import lru_cache


@lru_cache(maxsize=2)
def _database(uri: str):
    try:
        from pymongo import MongoClient
    except ImportError as exc:
        raise RuntimeError("MongoDB storage requires PyMongo. Install project dependencies with: python -m pip install -r requirements.txt") from exc
    client = MongoClient(uri, serverSelectionTimeoutMS=6000, connectTimeoutMS=6000)
    try:
        client.admin.command("ping")
    except Exception as exc:
        client.close()
        raise RuntimeError(f"Could not connect to MongoDB. Check MONGODB_URI, Atlas network access and database-user credentials: {exc}") from exc
    database = client[os.getenv("MONGODB_DB_NAME", "insuremap_ai")]
    database.decisions.create_index([("status", 1), ("source_name", 1)])
    database.audit.create_index([("created_at", -1)])
    return database


def _db():
    uri = os.getenv("MONGODB_URI", "").strip()
    if not uri:
        raise RuntimeError("MongoDB is not configured. Add MONGODB_URI to the project .env file, then restart the app.")
    return _database(uri)


def get_cached_run(cache_key: str):
    row = _db().run_cache.find_one({"_id": cache_key}, {"payload": 1})
    return row.get("payload") if row else None


def save_cached_run(cache_key: str, payload: list[dict]):
    _db().run_cache.replace_one(
        {"_id": cache_key},
        {"_id": cache_key, "payload": payload, "updated_at": datetime.now(timezone.utc)},
        upsert=True,
    )


def feedback():
    rows = _db().decisions.find(
        {"status": {"$in": ["approved", "edited"]}},
        {"source_name": 1, "target_field": 1, "rule": 1, "_id": 0},
    )
    return [{"source_name": r["source_name"], "target_field": r.get("target_field"), "rule": r.get("rule", {})} for r in rows]


def save_decision(source: str, target: str | None, rule: dict, status: str, note: str = ""):
    db = _db()
    doc = {"source_name": source, "target_field": target, "rule": rule, "status": status, "note": note, "created_at": datetime.now(timezone.utc)}
    db.decisions.insert_one(doc)
    db.audit.insert_one({"action": status, "payload": {"source": source, "target": target, "rule": rule, "note": note}, "created_at": datetime.now(timezone.utc)})


def record_event(action: str, payload: dict):
    _db().audit.insert_one({"action": action, "payload": payload, "created_at": datetime.now(timezone.utc)})


def audit_rows():
    rows = _db().audit.find({}, {"created_at": 1, "action": 1, "payload": 1, "_id": 0}).sort("created_at", -1).limit(200)
    return [{"timestamp": row.get("created_at"), "action": row.get("action"), "payload": row.get("payload")} for row in rows]
