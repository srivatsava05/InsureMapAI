"""Validation and normalization for target-schema JSON uploads."""


def normalize_target_fields(document) -> list[dict]:
    if isinstance(document, dict):
        fields = document.get("fields")
    elif isinstance(document, list):
        fields = document
    else:
        fields = None
    if not isinstance(fields, list) or not all(
        isinstance(item, dict) and "name" in item and "type" in item
        for item in fields
    ):
        raise ValueError("Expected a JSON object with a fields array or a field array; each field needs name and type.")
    return fields
