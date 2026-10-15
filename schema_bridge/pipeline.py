"""Mapping orchestration with heuristic preview and optional Gemini agent."""
from __future__ import annotations
import pandas as pd
import json, hashlib
from .profile import profile_frame
from .candidates import rank_candidates, relevant_feedback
from .llm import map_many_with_gemini, repair_with_gemini
from .models import MappingDecision, Rule
from .verify import verify_rule
from .storage import feedback, get_cached_run, save_cached_run, record_event

def heuristic_decision(profile: dict, candidates: list[dict]) -> MappingDecision:
    target=candidates[0]["target"] if candidates else None
    if target is None or candidates[0]["score"]<.28: return MappingDecision(decision="uncertain",reasoning="No candidate has sufficient local evidence.")
    name=profile["name"].upper(); samples=profile.get("samples",[])
    if "DATE" in name or "DT" in name or "date_like" in profile.get("patterns",[]):
        formats=[]
        for x in samples:
            s=str(x)
            for f,pat in [("%m%d%Y",8),("%y%m%d",6),("%Y-%m-%d",10),("%m/%d/%Y",10),("%m-%d-%Y",10)]:
                if len(s)==pat and f not in formats: formats.append(f)
        rule=Rule(type="DATE_PARSE",params={"formats":formats or ["%m%d%Y","%y%m%d","%Y-%m-%d"]})
    elif "PREM" in name or "AMT" in name or "RSV" in name or "PAID" in name:
        rule=Rule(type="NUMERIC_SCALE",params={"factor":.01 if "PREM" in name or "AMT" in name or "RSV" in name or "PAID" in name else 1})
    elif "CLM_STAT" in name:
        rule=Rule(type="LOOKUP",params={"map":{"O":"open","C":"closed","R":"reopened"},"default":None})
    elif "STAT" in name or "CD" in name:
        distinct=profile.get("distinct",[])
        if "STAT" in name: mapping={"A":"active","C":"cancelled","X":"expired","P":"pending"}
        elif "LOB" in name: mapping={"AUTO":"auto","HOME":"home","PROP":"property"}
        elif "COV" in name: mapping={"COLL":"collision","LIAB":"liability","COMP":"comprehensive"}
        else: mapping={str(v):str(v) for v in distinct}
        rule=Rule(type="LOOKUP",params={"map":mapping,"default":None})
    elif "LOB" in name:
        rule=Rule(type="LOOKUP",params={"map":{"AUTO":"auto","HOME":"home","PROP":"property"},"default":None})
    elif "COV" in name:
        rule=Rule(type="LOOKUP",params={"map":{"COLL":"collision","LIAB":"liability","COMP":"comprehensive"},"default":None})
    elif "FLG" in name or "indicator" in name:
        rule=Rule(type="LOOKUP",params={"map":{"Y":True,"N":False},"default":None})
    elif "NM" in name or "NAME" in name:
        rule=Rule(type="SPLIT",params={"delimiter":",","index":1})
    else: rule=Rule(type="COPY")
    return MappingDecision(decision="mapped",target_field=target["name"],rule=rule,reasoning="Local preview selected the highest-ranked target candidate; review before use.",evidence_quote=(profile.get("samples") or [None])[0])

def run_mapping(frame: pd.DataFrame, targets: list[dict], dictionary: str, mode: str="Preview") -> list[dict]:
    memory=feedback()
    cache_data={"csv":frame.to_csv(index=False),"targets":targets,"dictionary":dictionary,"mode":mode,"feedback":memory,"prompt_version":"v3-schema-constrained-batch"}
    cache_key=hashlib.sha256(json.dumps(cache_data,sort_keys=True,default=str).encode()).hexdigest()
    cached=get_cached_run(cache_key)
    if cached:
        from .models import VerifierResult
        for item in cached:
            item["decision"]=MappingDecision.model_validate(item["decision"])
            item["verification"]=VerifierResult.model_validate(item["verification"])
        return cached
    outputs=[]
    profiles=profile_frame(frame)
    gemini_decisions={}
    gemini_usage={}
    if mode=="Gemini":
        batch=[]
        for profile in profiles:
            candidates=rank_candidates(profile,targets,dictionary,memory)
            dictionary_lines=[line for line in dictionary.splitlines() if profile["name"].lower() in line.lower() or any(str(v) in line for v in profile.get("samples",[])[:2])]
            batch.append({"profile":profile,"candidates":[{"target":c["target"],"score":c["score"]} for c in candidates],"dictionary_evidence":dictionary_lines,"reviewer_feedback_examples":relevant_feedback(profile["name"],memory)})
        gemini_decisions,gemini_usage=map_many_with_gemini(batch,[t["name"] for t in targets])
    repair_requests=0
    for profile_index,profile in enumerate(profiles):
        candidates=rank_candidates(profile,targets,dictionary,memory)
        if mode=="Gemini":
            decision=gemini_decisions[profile["name"]]
            # Count the table-wide call once in aggregate token totals.
            usage=gemini_usage if profile_index==0 else {**gemini_usage,"prompt_tokens":0,"response_tokens":0}
        else:
            decision=heuristic_decision(profile,candidates); usage={"model":"local-hybrid-preview","prompt_tokens":0,"response_tokens":0}
        if decision.target_field:
            canonical=next((t["name"] for t in targets if t["name"].strip().casefold()==decision.target_field.strip().casefold()),None)
            if canonical:
                decision.target_field=canonical
        target=next((t for t in targets if t["name"]==decision.target_field),None)
        candidate_names={c["target"]["name"] for c in candidates}
        if decision.target_field and (not target or decision.target_field not in candidate_names):
            decision.decision="uncertain"; decision.target_field=None; decision.reasoning="Agent selected a target outside this column's retrieved schema candidates; blocked."
        verification=verify_rule(frame[profile["name"]],decision.rule,target or {},profile["type"])
        repair_count=0
        if mode=="Gemini":
            # Bound autonomous repair to two attempts. An unresolved rule always returns to a person.
            while not verification.passed and repair_count<2 and repair_requests<2:
                failing=[str(x) for x in profile.get("samples",[]) if x is not None]
                try:
                    revised,repair_usage=repair_with_gemini(profile,decision,verification.issues,failing)
                    repair_requests+=1
                    usage["prompt_tokens"]=usage.get("prompt_tokens",0)+repair_usage.get("prompt_tokens",0)
                    usage["response_tokens"]=usage.get("response_tokens",0)+repair_usage.get("response_tokens",0)
                    decision=revised; repair_count+=1
                    verification=verify_rule(frame[profile["name"]],decision.rule,target or {},profile["type"])
                except Exception:
                    break
        top_score=candidates[0]["score"] if candidates else 0
        agreement=float(bool(candidates and decision.target_field==candidates[0]["target"]["name"]))
        confidence=round(max(0,min(1,.55*top_score+.2*agreement+.25*float(verification.passed))),3)
        status="auto_accepted" if confidence>=.85 and verification.passed and decision.decision=="mapped" and decision.rule.type!="CUSTOM" else "needs_human"
        outputs.append({"source_field":profile["name"],"profile":profile,"candidates":candidates,"decision":decision,"target":target,"verification":verification,"confidence":confidence,"status":status,"usage":usage,"repair_count":repair_count})
    save_cached_run(cache_key,[{**item,"decision":item["decision"].model_dump(),"verification":item["verification"].model_dump()} for item in outputs])
    for item in outputs:
        record_event("mapping_proposed",{"trace_id":f"{cache_key[:12]}:{item['source_field']}","source_field":item["source_field"],"target_field":item["decision"].target_field,"rule_type":item["decision"].rule.type,"confidence":item["confidence"],"status":item["status"],"verifier_passed":item["verification"].passed,"issues":item["verification"].issues,"model":item["usage"].get("model"),"tokens":item["usage"].get("prompt_tokens",0)+item["usage"].get("response_tokens",0),"repair_count":item["repair_count"]})
    return outputs
