"""Gemini JSON adapter using the public generateContent REST endpoint."""
from __future__ import annotations
import json, os, time, urllib.request, urllib.error
from .models import MappingDecision


def _decode_params(value):
    """Decode rule parameters returned as JSON text for GenerateContent Schema compatibility."""
    params = json.loads(value) if isinstance(value, str) else value
    if not isinstance(params, dict):
        raise ValueError("Gemini rule params must decode to a JSON object.")
    return params

def map_many_with_gemini(items: list[dict], allowed_targets: list[str] | None = None) -> tuple[dict[str, MappingDecision], dict]:
    """Map a whole dataset's columns in one Gemini request to conserve free quota."""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Add GEMINI_API_KEY in .env to use Gemini.")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    target_names=sorted(set(allowed_targets or [c["target"]["name"] for item in items for c in item.get("candidates",[])]))
    decision_schema = {"type":"OBJECT", "properties":{
        "source_field":{"type":"STRING"},
        "decision":{"type":"STRING","enum":["mapped","uncertain","no_match"]},
        "target_field":{"type":"STRING","enum":target_names,"nullable":True},
        "rule":{"type":"OBJECT","properties":{"type":{"type":"STRING","enum":["COPY","CAST","TRIM_CASE","DATE_PARSE","SPLIT","CONCAT","LOOKUP","DEFAULT","REGEX_EXTRACT","NUMERIC_SCALE","CUSTOM"]},"params":{"type":"STRING","description":"JSON-encoded object containing this rule's parameters"}},"required":["type","params"]},
        "reasoning":{"type":"STRING"},"evidence_quote":{"type":"STRING","nullable":True}},
        "required":["source_field","decision","target_field","rule","reasoning","evidence_quote"]}
    schema={"type":"OBJECT","properties":{"mappings":{"type":"ARRAY","items":decision_schema}},"required":["mappings"]}
    prompt={"allowed_target_names":target_names,"columns":items}
    body={"system_instruction":{"parts":[{"text":"Map every supplied insurance source column exactly once using only its supplied evidence. Select a target only from that column's candidates. Copy the target name exactly, including spelling and case; target_field must be one of allowed_target_names, or null when decision is uncertain/no_match. Output fixed-vocabulary transformation rules; never output code. Put rule params in the params field as a JSON-encoded string whose decoded value is an object. For code columns provide a LOOKUP for every observed distinct value, mapping unknown values to null. For dates use DATE_PARSE and list observed formats. Quote evidence exactly; do not invent it."}]},
          "contents":[{"role":"user","parts":[{"text":json.dumps(prompt,ensure_ascii=False)}]}],
          "generationConfig":{"responseMimeType":"application/json","responseSchema":schema,"temperature":0.1}}
    url=f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    req=urllib.request.Request(url,data=json.dumps(body).encode(),headers={"Content-Type":"application/json","x-goog-api-key":key},method="POST")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req,timeout=60) as response: raw=json.loads(response.read())
            parsed=json.loads(raw["candidates"][0]["content"]["parts"][0]["text"])
            decisions={}
            for item in parsed["mappings"]:
                item["rule"]["params"]=_decode_params(item["rule"].get("params","{}"))
                name=item.pop("source_field")
                if name in decisions: raise ValueError(f"Gemini returned duplicate source field: {name}")
                decisions[name]=MappingDecision.model_validate(item)
            expected={item["profile"]["name"] for item in items}
            if set(decisions)!=expected: raise ValueError("Gemini did not return exactly one mapping for every source field.")
            usage=raw.get("usageMetadata",{})
            return decisions,{"model":model,"prompt_tokens":usage.get("promptTokenCount",0),"response_tokens":usage.get("candidatesTokenCount",0)}
        except urllib.error.HTTPError as e:
            detail=e.read().decode(errors="replace")[:400]
            if 500<=e.code<600 and attempt<3:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Gemini API error ({e.code}): {detail}") from e
        except (KeyError,IndexError,json.JSONDecodeError,ValueError) as e:
            if attempt==0:
                prompt["format_retry_note"]="Return exactly one valid mapping for every source_field, with valid JSON and required keys."
                body["contents"][0]["parts"][0]["text"]=json.dumps(prompt,ensure_ascii=False)
                req=urllib.request.Request(url,data=json.dumps(body).encode(),headers={"Content-Type":"application/json","x-goog-api-key":key},method="POST")
                continue
            raise RuntimeError(f"Gemini returned invalid structured output after one retry: {e}") from e

def map_with_gemini(profile: dict, candidates: list[dict], dictionary_lines: list[str], prior_feedback: list[dict] | None = None) -> tuple[MappingDecision, dict]:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Add GEMINI_API_KEY in .env to use Gemini. Preview mode does not need a key.")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    schema = {"type":"OBJECT", "properties":{
        "decision":{"type":"STRING","enum":["mapped","uncertain","no_match"]},
        "target_field":{"type":"STRING","nullable":True},
        "rule":{"type":"OBJECT","properties":{"type":{"type":"STRING","enum":["COPY","CAST","TRIM_CASE","DATE_PARSE","SPLIT","CONCAT","LOOKUP","DEFAULT","REGEX_EXTRACT","NUMERIC_SCALE","CUSTOM"]},"params":{"type":"STRING","description":"JSON-encoded object containing this rule's parameters"}},"required":["type","params"]},
        "reasoning":{"type":"STRING"},"evidence_quote":{"type":"STRING","nullable":True}},
        "required":["decision","target_field","rule","reasoning","evidence_quote"]}
    prompt = {"column_profile":profile,"candidates":[{"target":c["target"],"score":c["score"]} for c in candidates],"dictionary_evidence":dictionary_lines,"reviewer_feedback_examples":prior_feedback or []}
    body = {"system_instruction":{"parts":[{"text":"Map insurance data columns using only supplied evidence. Select a target only from candidates or return uncertain/no_match. Output a fixed-vocabulary transformation rule; never output code. Put rule parameters in the params field as a JSON-encoded string whose decoded value is an object. Treat reviewer examples as helpful but not authoritative when the new profile contradicts them. For code columns provide a LOOKUP for every observed distinct value, mapping unknown values to null and explaining unmapped values. For dates use DATE_PARSE and list observed formats. Quote evidence exactly; do not invent it."}]},
            "contents":[{"role":"user","parts":[{"text":json.dumps(prompt, ensure_ascii=False)}]}],
            "generationConfig":{"responseMimeType":"application/json","responseSchema":schema,"temperature":0.1}}
    url=f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    req=urllib.request.Request(url,data=json.dumps(body).encode(),headers={"Content-Type":"application/json","x-goog-api-key":key},method="POST")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=45) as response: raw=json.loads(response.read())
            text=raw["candidates"][0]["content"]["parts"][0]["text"]
            response_data=json.loads(text)
            response_data["rule"]["params"]=_decode_params(response_data["rule"].get("params", "{}"))
            decision=MappingDecision.model_validate(response_data)
            usage=raw.get("usageMetadata",{})
            return decision,{"model":model,"prompt_tokens":usage.get("promptTokenCount",0),"response_tokens":usage.get("candidatesTokenCount",0)}
        except urllib.error.HTTPError as e:
            detail=e.read().decode(errors="replace")[:400]
            if 500<=e.code<600 and attempt<3:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Gemini API error ({e.code}): {detail}") from e
        except (KeyError,IndexError,json.JSONDecodeError,ValueError) as e:
            if attempt==0:
                prompt["format_retry_note"]="The previous model response failed JSON contract validation. Recheck required keys, rule enum and types; return valid JSON only."
                body["contents"][0]["parts"][0]["text"]=json.dumps(prompt,ensure_ascii=False)
                req=urllib.request.Request(url,data=json.dumps(body).encode(),headers={"Content-Type":"application/json","x-goog-api-key":key},method="POST")
                continue
            raise RuntimeError(f"Gemini returned invalid structured output after one retry: {e}") from e

def repair_with_gemini(profile: dict, decision: MappingDecision, issues: list[str], failing_values: list[str]) -> tuple[MappingDecision, dict]:
    """Ask Gemini to revise only an allowlisted rule after concrete verifier failures."""
    key=os.getenv("GEMINI_API_KEY","").strip()
    if not key: raise RuntimeError("GEMINI_API_KEY is required for the Gemini repair agent.")
    model=os.getenv("GEMINI_MODEL","gemini-2.5-flash").strip()
    schema={"type":"OBJECT","properties":{"type":{"type":"STRING","enum":["COPY","CAST","TRIM_CASE","DATE_PARSE","SPLIT","CONCAT","LOOKUP","DEFAULT","REGEX_EXTRACT","NUMERIC_SCALE","CUSTOM"]},"params":{"type":"STRING","description":"JSON-encoded object containing this rule's parameters"},"explanation":{"type":"STRING"}},"required":["type","params","explanation"]}
    context={"profile":profile,"current_rule":decision.rule.model_dump(),"verifier_issues":issues,"failing_samples":failing_values[:10]}
    body={"system_instruction":{"parts":[{"text":"Repair the proposed insurance data transformation using only the supplied profile, verifier issues and failing examples. Return one allowlisted rule, put its params as a JSON-encoded string whose decoded value is an object, and give a short explanation. Do not output code. If no safe repair exists, return CUSTOM; it will not execute."}]},"contents":[{"role":"user","parts":[{"text":json.dumps(context,ensure_ascii=False)}]}],"generationConfig":{"responseMimeType":"application/json","responseSchema":schema,"temperature":0.1}}
    url=f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    req=urllib.request.Request(url,data=json.dumps(body).encode(),headers={"Content-Type":"application/json","x-goog-api-key":key},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=45) as response: raw=json.loads(response.read())
        parsed=json.loads(raw["candidates"][0]["content"]["parts"][0]["text"])
        revised=MappingDecision.model_validate({**decision.model_dump(),"rule":{"type":parsed["type"],"params":_decode_params(parsed.get("params", "{}"))},"reasoning":(decision.reasoning+" Repair: "+parsed.get("explanation",""))[:300]})
        usage=raw.get("usageMetadata",{})
        return revised,{"model":model,"prompt_tokens":usage.get("promptTokenCount",0),"response_tokens":usage.get("candidatesTokenCount",0)}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Gemini repair API error ({e.code}): {e.read().decode(errors='replace')[:400]}") from e
