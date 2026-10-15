from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from schema_bridge.models import Rule, MappingDecision
from schema_bridge.engine import apply_rule, sql_expression
from schema_bridge.verify import verify_rule
from schema_bridge.pipeline import heuristic_decision, run_mapping
from schema_bridge.candidates import rank_candidates, relevant_feedback
from schema_bridge import storage
from schema_bridge.passport import evidence_passport, passport_is_current
from schema_bridge.schema import normalize_target_fields
from schema_bridge import llm


ROOT = Path(__file__).resolve().parents[1]
TARGETS = json.loads((ROOT / "data/target_schema.json").read_text())["fields"]
DICTIONARY = (ROOT / "data/data_dictionary.txt").read_text()


class MemoryCursor(list):
    def sort(self, field, direction=1):
        self[:] = sorted(self, key=lambda row: row.get(field), reverse=direction < 0)
        return self

    def limit(self, count):
        del self[count:]
        return self


class MemoryCollection:
    def __init__(self):
        self.documents = []

    def create_index(self, *_args, **_kwargs):
        return None

    def find_one(self, query, projection=None):
        doc = next((row for row in self.documents if all(row.get(k) == v for k, v in query.items())), None)
        return dict(doc) if doc else None

    def replace_one(self, query, document, upsert=False):
        for index, row in enumerate(self.documents):
            if all(row.get(k) == v for k, v in query.items()):
                self.documents[index] = dict(document)
                return
        if upsert:
            self.documents.append(dict(document))

    def insert_one(self, document):
        self.documents.append(dict(document))

    def find(self, query=None, projection=None):
        query = query or {}
        rows = []
        for row in self.documents:
            matched = True
            for key, wanted in query.items():
                actual = row.get(key)
                if isinstance(wanted, dict) and "$in" in wanted:
                    matched &= actual in wanted["$in"]
                else:
                    matched &= actual == wanted
            if matched:
                rows.append({k: v for k, v in row.items() if k != "_id"})
        return MemoryCursor(rows)


class MemoryDatabase:
    def __init__(self):
        self.collections = {name: MemoryCollection() for name in ("decisions", "audit", "run_cache")}

    def __getitem__(self, name):
        return self.collections[name]

    def __getattr__(self, name):
        try:
            return self.collections[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class TransformationTests(unittest.TestCase):
    def test_all_rule_types_are_handled_and_nulls_preserved(self):
        cases = [
            ("COPY", {}, " x ", " x "),
            ("CAST", {"type": "integer"}, "12.0", 12),
            ("TRIM_CASE", {"mode": "upper"}, " x ", "X"),
            ("DATE_PARSE", {"formats": ["%m%d%Y"]}, "01022024", "2024-01-02"),
            ("SPLIT", {"delimiter": ",", "index": 1}, "Smith, Asha", "Asha"),
            ("CONCAT", {"value": "fixed"}, "x", "fixed"),
            ("LOOKUP", {"map": {"A": "active"}}, "A", "active"),
            ("DEFAULT", {"value": "fallback"}, "", "fallback"),
            ("REGEX_EXTRACT", {"pattern": r"(\d+)", "group": 1}, "id42", "42"),
            ("NUMERIC_SCALE", {"factor": .01}, "1234", 12.34),
            ("CUSTOM", {}, "x", None),
        ]
        for kind, params, value, expected in cases:
            with self.subTest(rule=kind):
                self.assertEqual(apply_rule(value, Rule(type=kind, params=params)), expected)
                self.assertIsNone(apply_rule(None, Rule(type=kind, params=params)))

    def test_sql_generation_quotes_identifiers_and_lookup_literals(self):
        self.assertEqual(sql_expression('a"b', Rule(type="COPY")), '"a""b"')
        expr = sql_expression("code", Rule(type="LOOKUP", params={"map": {"O'K": "open"}}))
        self.assertIn("O''K", expr)


class VerificationTests(unittest.TestCase):
    def test_rejects_required_nulls_bad_dates_and_unmapped_codes(self):
        date_result = verify_rule(pd.Series(["01022024", "not-a-date"]), Rule(type="DATE_PARSE", params={"formats": ["%m%d%Y"]}), {"type": "date", "required": True}, "string")
        self.assertFalse(date_result.passed)
        self.assertTrue(any("null" in issue.lower() or "98%" in issue for issue in date_result.issues))
        lookup_result = verify_rule(pd.Series(["A", "Z"]), Rule(type="LOOKUP", params={"map": {"A": "active"}}), {"type": "string", "allowed_values": ["active"]}, "string")
        self.assertFalse(lookup_result.passed)
        self.assertTrue(any("Unmapped" in issue for issue in lookup_result.issues))

    def test_accepts_valid_numeric_and_boolean_outputs(self):
        amount = verify_rule(pd.Series(["100", "250"]), Rule(type="NUMERIC_SCALE", params={"factor": .01}), {"type": "number"}, "numeric")
        self.assertTrue(amount.passed)
        flag = verify_rule(pd.Series(["Y", "N"]), Rule(type="LOOKUP", params={"map": {"Y": True, "N": False}}), {"type": "boolean"}, "string")
        self.assertTrue(flag.passed)


class RetrievalAndPipelineTests(unittest.TestCase):
    def test_claim_status_heuristic_uses_claim_vocabulary(self):
        profile = {"name": "CLM_STAT", "type": "string", "patterns": ["code_like"], "distinct": ["O", "C", "R"], "samples": ["O"]}
        decision = heuristic_decision(profile, [{"target": next(t for t in TARGETS if t["name"] == "claim_status"), "score": .9}])
        self.assertEqual(decision.rule.params["map"], {"O": "open", "C": "closed", "R": "reopened"})

    def test_candidate_rank_and_feedback_relevance(self):
        prof = {"name": "POL_NO", "type": "string", "patterns": [], "samples": ["P-000001"]}
        ranked = rank_candidates(prof, TARGETS, DICTIONARY)
        self.assertEqual(ranked[0]["target"]["name"], "policy_number")
        memory = [{"source_name": "POL_NO", "target_field": "policy_number"}]
        self.assertEqual(len(relevant_feedback("contract_key", memory)), 1)

    def test_cache_roundtrip_uses_mocked_mongodb(self):
        memory_db = MemoryDatabase()
        with patch.object(storage, "_db", return_value=memory_db):
            frame = pd.DataFrame({"POL_NO": ["P-1", "P-2"]})
            first = run_mapping(frame, TARGETS, DICTIONARY, "Preview")
            second = run_mapping(frame, TARGETS, DICTIONARY, "Preview")
            self.assertEqual(first[0]["decision"].model_dump(), second[0]["decision"].model_dump())
            self.assertEqual(first[0]["verification"].model_dump(), second[0]["verification"].model_dump())

    def test_failed_gemini_rule_gets_at_most_two_repairs(self):
        import schema_bridge.pipeline as pipeline
        bad_decision = MappingDecision(decision="mapped", target_field="effective_date", rule=Rule(type="DATE_PARSE", params={"formats": ["%Y"]}))
        with patch.object(storage, "_db", return_value=MemoryDatabase()), \
                 patch.object(pipeline, "map_many_with_gemini", return_value=({"EFF_DT": bad_decision}, {"model": "fake", "prompt_tokens": 1, "response_tokens": 1})), \
                 patch.object(pipeline, "repair_with_gemini", return_value=(bad_decision, {"prompt_tokens": 1, "response_tokens": 1})) as repair:
            result = run_mapping(pd.DataFrame({"EFF_DT": ["01022024"]}), TARGETS, DICTIONARY, "Gemini")
            self.assertEqual(result[0]["repair_count"], 2)
            self.assertEqual(repair.call_count, 2)
            self.assertEqual(result[0]["status"], "needs_human")

    def test_evidence_passport_detects_source_schema_and_dictionary_changes(self):
        frame = pd.DataFrame({"POL_NO": ["P-1"]})
        with patch.object(storage, "_db", return_value=MemoryDatabase()):
            item = run_mapping(frame, TARGETS, DICTIONARY, "Preview")[0]
            passport = evidence_passport(frame, TARGETS, DICTIONARY, item)
            self.assertTrue(passport_is_current(passport, frame, TARGETS, DICTIONARY))
            self.assertFalse(passport_is_current(passport, frame.assign(POL_NO=["P-2"]), TARGETS, DICTIONARY))
            self.assertFalse(passport_is_current(passport, frame, TARGETS[:-1], DICTIONARY))
            self.assertFalse(passport_is_current(passport, frame, TARGETS, DICTIONARY + "\nnew note"))

    def test_mongodb_storage_persists_decisions_feedback_audit_and_cache(self):
        memory_db = MemoryDatabase()
        with patch.object(storage, "_db", return_value=memory_db):
            storage.save_decision("POL_NO", "policy_number", {"type": "COPY", "params": {}}, "approved", "checked")
            storage.save_decision("BAD", None, {}, "rejected", "not mapped")
            self.assertEqual(storage.feedback()[0]["target_field"], "policy_number")
            storage.save_cached_run("key", [{"value": 7}])
            self.assertEqual(storage.get_cached_run("key"), [{"value": 7}])
            rows = storage.audit_rows()
            self.assertEqual(len(rows), 2)
            self.assertIn(rows[0]["action"], {"approved", "rejected"})

    def test_gemini_mapping_uses_supported_schema_and_decodes_rule_params(self):
        response_data = {"candidates": [{"content": {"parts": [{"text": json.dumps({"decision": "mapped", "target_field": "claim_status", "rule": {"type": "LOOKUP", "params": '{"map":{"O":"open"},"default":null}'}, "reasoning": "Code evidence", "evidence_quote": "O"})}]}}]}
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(response_data).encode()
        with patch.dict("os.environ", {"GEMINI_API_KEY": "unit-test-key", "GEMINI_MODEL": "gemini-2.5-flash"}), \
             patch.object(llm.urllib.request, "urlopen", return_value=response) as urlopen:
            decision, usage = llm.map_with_gemini({"name": "CLM_STAT"}, [], [])
        self.assertEqual(decision.rule.params, {"map": {"O": "open"}, "default": None})
        self.assertEqual(usage["model"], "gemini-2.5-flash")
        request_body = json.loads(urlopen.call_args.args[0].data)
        params_schema = request_body["generationConfig"]["responseSchema"]["properties"]["rule"]["properties"]["params"]
        self.assertEqual(params_schema["type"], "STRING")
        self.assertNotIn("additionalProperties", json.dumps(request_body))

    def test_gemini_batch_maps_each_source_column_in_one_request(self):
        mapping = {"source_field": "CLM_STAT", "decision": "mapped", "target_field": "claim_status", "rule": {"type": "LOOKUP", "params": '{"map":{"O":"open"}}'}, "reasoning": "Code evidence", "evidence_quote": "O"}
        response_data = {"candidates": [{"content": {"parts": [{"text": json.dumps({"mappings": [mapping]})}]}}]}
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(response_data).encode()
        item = {"profile": {"name": "CLM_STAT"}, "candidates": [{"target": {"name": "claim_status"}, "score": 0.9}], "dictionary_evidence": [], "reviewer_feedback_examples": []}
        with patch.dict("os.environ", {"GEMINI_API_KEY": "unit-test-key", "GEMINI_MODEL": "gemini-2.5-flash"}), \
             patch.object(llm.urllib.request, "urlopen", return_value=response) as urlopen:
            decisions, usage = llm.map_many_with_gemini([item])
        self.assertEqual(decisions["CLM_STAT"].rule.params, {"map": {"O": "open"}})
        self.assertEqual(usage["model"], "gemini-2.5-flash")
        self.assertEqual(urlopen.call_count, 1)
        request_body = json.loads(urlopen.call_args.args[0].data)
        params_schema = request_body["generationConfig"]["responseSchema"]["properties"]["mappings"]["items"]["properties"]["rule"]["properties"]["params"]
        self.assertEqual(params_schema["type"], "STRING")
        target_schema = request_body["generationConfig"]["responseSchema"]["properties"]["mappings"]["items"]["properties"]["target_field"]
        self.assertIn("claim_status", target_schema["enum"])
        self.assertNotIn("additionalProperties", json.dumps(request_body))

    def test_gemini_repair_uses_supported_schema_and_decodes_rule_params(self):
        response_data = {"candidates": [{"content": {"parts": [{"text": json.dumps({"type": "LOOKUP", "params": '{"map":{"O":"open"}}', "explanation": "Mapped known code"})}]}}]}
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(response_data).encode()
        decision = MappingDecision(decision="mapped", target_field="claim_status", rule=Rule(type="COPY"))
        with patch.dict("os.environ", {"GEMINI_API_KEY": "unit-test-key", "GEMINI_MODEL": "gemini-2.5-flash"}), \
             patch.object(llm.urllib.request, "urlopen", return_value=response) as urlopen:
            repaired, _usage = llm.repair_with_gemini({"name": "CLM_STAT"}, decision, ["unmapped code"], ["O"])
        self.assertEqual(repaired.rule.params, {"map": {"O": "open"}})
        request_body = json.loads(urlopen.call_args.args[0].data)
        params_schema = request_body["generationConfig"]["responseSchema"]["properties"]["params"]
        self.assertEqual(params_schema["type"], "STRING")
        self.assertNotIn("additionalProperties", json.dumps(request_body))


class EvaluationDataTests(unittest.TestCase):
    def test_target_schema_accepts_object_and_list_shapes(self):
        field = {"name": "policy_number", "type": "string"}
        self.assertEqual(normalize_target_fields([field]), [field])
        self.assertEqual(normalize_target_fields({"fields": [field]}), [field])
        with self.assertRaises(ValueError):
            normalize_target_fields({"fields": [{"name": "missing_type"}]})

    def test_generated_fixtures_match_gold_columns_and_expected_row_counts(self):
        gold = json.loads((ROOT / "data/gold_mapping.json").read_text())
        cases = [("LEGACY_POLICY", "policy", 300), ("LEGACY_CLAIM", "claim", 200), ("LEGACY_POLICY_V2", "policy_v2", 300)]
        for filename, key, rows in cases:
            with self.subTest(dataset=filename):
                frame = pd.read_csv(ROOT / f"data/generated/{filename}.csv")
                self.assertEqual(len(frame), rows)
                self.assertEqual(set(frame.columns), set(gold[key]))


if __name__ == "__main__":
    unittest.main()
