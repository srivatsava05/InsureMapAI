"""Hybrid lexical and semantic-style candidate retrieval (RAG)."""
from __future__ import annotations
import re
from difflib import SequenceMatcher

TERMS={
    "pol":"policy", "contract":"policy", "key":"number", "no":"number", "num":"number",
    "ins":"insured", "insured":"customer", "cust":"customer", "nm":"name", "label":"name",
    "eff":"effective", "start":"effective", "end":"expiration", "exp":"expiration", "on":"date", "dt":"date", "date":"date",
    "prem":"premium", "amt":"amount", "minor":"cents currency", "written":"written premium",
    "stat":"status", "lifecycle":"status", "cd":"code", "flg":"flag", "indicator":"flag",
    "lob":"line business product", "family":"line business product", "producer":"agent", "agt":"agent",
    "tel":"phone telephone", "postal":"zip postal code", "primary":"five digit", "suffix":"zip4",
    "street":"address", "municipality":"city", "asset":"vehicle", "ref":"identifier",
    "loss":"loss", "rpt":"reported", "reported":"reported", "rsv":"reserve", "paid":"paid", "adj":"adjuster",
    "deductible":"deductible", "coverage":"coverage limit", "kind":"coverage type", "termination":"cancellation",
}

ALIASES={
 "policy_number":"contract identifier policy number policy key", "effective_date":"start date inception effective start",
 "expiration_date":"end date expiry expiration end", "premium_amount":"written premium premium amount cents currency",
 "policy_status":"lifecycle status policy status code", "line_of_business":"product family insurance line business",
 "producer_id":"agent producer reference", "risk_state":"insured state risk state", "postal_code":"zip postal code",
 "full_name":"insured customer named insured name", "first_name":"insured given first name", "last_name":"insured family surname",
 "phone":"telephone contact phone", "email":"contact email", "street_address":"insured street address",
 "city":"mailing municipality city", "deductible_amount":"deductible amount cents", "limit_amount":"coverage limit amount cents",
 "coverage_type":"coverage kind type code", "vehicle_year":"vehicle model year", "vehicle_id":"vehicle vin asset identifier",
 "renewal_flag":"renewal indicator flag", "claim_number":"claim identifier number", "loss_date":"loss date of loss",
 "reported_date":"claim reported date", "claim_status":"claim lifecycle status", "reserve_amount":"claim reserve amount",
 "paid_amount":"claim indemnity paid amount", "cause_code":"loss cause code", "adjuster_id":"claim adjuster reference",
 "loss_state":"loss location state", "injury_flag":"claim injury indicator", "closed_date":"claim closure date",
 "expense_amount":"claim expense amount", "recovery_amount":"claim recovery amount",
}

SOURCE_ALIASES={
 "pol no":"policy number identifier", "contract key":"policy number identifier", "ins nm":"insured full name named insured",
 "customer label":"insured full name named insured", "eff dt":"effective date inception", "start on":"effective date inception",
 "exp dt":"expiration date expiry", "end on":"expiration date expiry", "prem amt":"premium amount cents written premium",
 "written premium minor":"premium amount cents written premium", "stat cd":"policy status lifecycle code",
 "lifecycle":"policy status lifecycle code", "lob cd":"line of business product family", "product family":"line of business product family",
 "agt id":"producer agent identifier", "producer ref":"producer agent identifier", "st":"risk state", "zip5":"five digit postal zip code",
 "postal primary":"five digit postal zip code", "phone":"contact phone telephone", "contact tel":"contact phone telephone",
 "email":"contact email", "contact mail":"contact email", "addr1":"street address", "street line":"street address",
 "city":"mailing city", "municipality":"mailing city", "deduct amt":"deductible amount cents", "deductible minor":"deductible amount cents",
 "limit amt":"coverage limit amount cents", "coverage limit minor":"coverage limit amount cents", "cov cd":"coverage type code",
 "coverage kind":"coverage type code", "veh yr":"vehicle model year", "model year":"vehicle model year", "vin":"vehicle id vin",
 "asset ref":"vehicle id vin", "renew flg":"renewal flag", "renewal indicator":"renewal flag",
 "clm no":"claim number identifier", "loss dt":"loss date", "rpt dt":"reported date", "clm stat":"claim status lifecycle",
 "rsv amt":"reserve amount", "paid amt":"paid amount", "cause cd":"cause of loss code", "adj id":"adjuster identifier",
 "loss st":"loss state", "injury flg":"injury flag", "closed dt":"claim closure date", "expense amt":"claim expense amount",
 "recovery amt":"claim recovery amount",
}

def expand(text: str) -> str:
    base=normalize(text)
    words=base.split()
    extra=[]
    for word in words:
        if word in TERMS: extra.extend(normalize(TERMS[word]).split())
    return " ".join(words+extra)

def normalize(text: str) -> str:
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(text))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

def rank_candidates(profile: dict, targets: list[dict], dictionary: str = "", feedback: list[dict] | None = None) -> list[dict]:
    raw_name=normalize(profile["name"])
    name = expand(profile["name"]) + " " + expand(SOURCE_ALIASES.get(raw_name,""))
    samples = " ".join(map(str, profile.get("samples", []))).lower()
    source_words=set(raw_name.split()); source_alias_words=set(expand(SOURCE_ALIASES.get(raw_name,"")).split())
    hits=[]
    for line in dictionary.splitlines():
        line_words=set(normalize(line).split())
        if (source_words and len(source_words & line_words)/len(source_words)>=.5) or (source_alias_words and len(source_alias_words & line_words)/len(source_alias_words)>=.5): hits.append(line.strip())
    result = []
    for target in targets:
        haystack = expand(target["name"] + " " + target.get("description", "") + " " + target.get("entity", "") + " " + ALIASES.get(target["name"],""))
        name_score = SequenceMatcher(None,name,haystack).ratio()
        words = set(name.split())
        lexical = len(words & set(haystack.split())) / max(1, len(words))
        type_ok = float(profile["type"] == target.get("type") or target.get("type") == "string" or profile["type"] == "string")
        pattern_match = 0.0
        if "date_like" in profile.get("patterns", []) and any(w in haystack for w in ("date", "effective", "expiration", "loss", "reported")): pattern_match = 1.0
        if "code_like" in profile.get("patterns", []) and any(w in haystack for w in ("status", "state", "line", "code", "type")): pattern_match = max(pattern_match, .8)
        if "numeric_like" in profile.get("patterns", []) and any(w in haystack for w in ("amount", "premium", "reserve", "paid", "limit")): pattern_match = max(pattern_match, .8)
        fboost = 0.0
        for fb in feedback or []:
            fb_name=normalize(fb.get("source_name", ""))
            fb_expanded=expand(fb_name)+" "+expand(SOURCE_ALIASES.get(fb_name,""))
            overlap=len(set(name.split()) & set(fb_expanded.split()))/max(1,min(len(set(name.split())),len(set(fb_expanded.split()))))
            if overlap>=.6 and fb.get("target_field") == target["name"]: fboost = max(fboost,.25)
        # Small local corpus, so transparent hybrid retrieval is a useful fallback to embeddings.
        evidence_overlap = 0.0
        if hits:
            evidence=expand(" ".join(hits))
            evidence_overlap=len(set(evidence.split()) & set(haystack.split()))/max(1,len(set(evidence.split())))
        score = min(1, .34 * name_score + .24 * lexical + .18 * type_ok + .16 * pattern_match + .06 * evidence_overlap + fboost)
        result.append({"target": target, "score": round(score, 4), "name_similarity": round(name_score, 3), "type_match": bool(type_ok), "pattern_match": round(pattern_match, 2), "dictionary_hits": hits[:2], "feedback_boost": fboost})
    return sorted(result, key=lambda x: x["score"], reverse=True)[:5]

def relevant_feedback(source_name: str, memory: list[dict]) -> list[dict]:
    raw=normalize(source_name); source=set((expand(raw)+" "+expand(SOURCE_ALIASES.get(raw,""))).split()); found=[]
    for item in memory:
        old=normalize(item.get("source_name","")); other=set((expand(old)+" "+expand(SOURCE_ALIASES.get(old,""))).split())
        overlap=len(source & other)/max(1,min(len(source),len(other)))
        if overlap>=.6: found.append(item)
    return found[:3]
