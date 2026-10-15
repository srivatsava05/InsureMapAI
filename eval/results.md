# Synthetic baseline results

> These results use hand-authored synthetic examples and the local heuristic preview. They are not Gemini results or evidence of carrier performance.

## LEGACY_POLICY

- Columns: 25
- Top-1 mapping accuracy: 68.0%
- Top-3 candidate recall: 100.0%
- Rule verifier pass rate: 84.0%
- Auto-accept precision: not measurable (no auto-accepted mappings) (0 auto-accepted mappings)
- Human-review share: 100.0%
- Local evaluation runtime: 0.315 seconds; tokens: 0 (no Gemini calls)

### Example mismatches

- `INS_NM` expected `full_name` but suggested `last_name`; top candidates: last_name, first_name, full_name.
- `ZIP4` expected `None` but suggested `coverage_type`; top candidates: coverage_type, vehicle_id, postal_code.
- `LIMIT_AMT` expected `limit_amount` but suggested `coverage_type`; top candidates: coverage_type, limit_amount, vehicle_id.

## LEGACY_CLAIM

- Columns: 15
- Top-1 mapping accuracy: 80.0%
- Top-3 candidate recall: 92.9%
- Rule verifier pass rate: 86.7%
- Auto-accept precision: 100.0% (1 auto-accepted mappings)
- Human-review share: 93.3%
- Local evaluation runtime: 0.125 seconds; tokens: 0 (no Gemini calls)

### Example mismatches

- `RPT_DT` expected `reported_date` but suggested `cause_code`; top candidates: cause_code, coverage_type, vehicle_id.
- `RSV_AMT` expected `reserve_amount` but suggested `vehicle_id`; top candidates: vehicle_id, reserve_amount, coverage_type.
- `SRC_SYS` expected `None` but suggested `cause_code`; top candidates: cause_code, risk_state, postal_code.

## LEGACY_POLICY_V2

- Columns: 25
- Top-1 mapping accuracy: 76.0%
- Top-3 candidate recall: 100.0%
- Rule verifier pass rate: 80.0%
- Auto-accept precision: 100.0% (3 auto-accepted mappings)
- Human-review share: 88.0%
- Local evaluation runtime: 0.316 seconds; tokens: 0 (no Gemini calls)

### Example mismatches

- `customer_label` expected `full_name` but suggested `last_name`; top candidates: last_name, full_name, risk_state.
- `postal_suffix` expected `None` but suggested `postal_code`; top candidates: postal_code, coverage_type, vehicle_id.
- `created_on` expected `None` but suggested `closed_date`; top candidates: closed_date, reported_date, expiration_date.

## Cross-schema feedback ablation

- Donor: `LEGACY_POLICY` hand-authored mapping corrections; evaluation variant: `LEGACY_POLICY_V2` (25 renamed fields).
- Top-1 without feedback: 76.0%; with feedback: 80.0%.
- Wrong-to-correct transitions: 1; correct-to-wrong regressions: 0.
- This is an oracle-style simulated feedback ablation, not a live reviewer study. The renamed variant shares the data generator and semantics, so it is not independent generalization evidence. See `feedback_comparison.transitions` in `results.json` for field-level outcomes.

## Interpretation

This is a small synthetic heuristic baseline, not an independent benchmark or Gemini performance result. The gold file is hand-written and the V2 data shares the same synthetic process. Low precision/coverage means suggestions must remain in human review.
