"""Typed contracts shared across the mapping pipeline."""
from typing import Any, Literal
from pydantic import BaseModel, Field

RuleType = Literal["COPY", "CAST", "TRIM_CASE", "DATE_PARSE", "SPLIT", "CONCAT", "LOOKUP", "DEFAULT", "REGEX_EXTRACT", "NUMERIC_SCALE", "CUSTOM"]

class Rule(BaseModel):
    type: RuleType
    params: dict[str, Any] = Field(default_factory=dict)

class MappingDecision(BaseModel):
    decision: Literal["mapped", "uncertain", "no_match"] = "uncertain"
    target_field: str | None = None
    rule: Rule = Field(default_factory=lambda: Rule(type="COPY"))
    reasoning: str = ""
    evidence_quote: str | None = None

class VerifierResult(BaseModel):
    passed: bool
    pass_rate: float
    issues: list[str] = Field(default_factory=list)
    preview: list[dict[str, Any]] = Field(default_factory=list)

