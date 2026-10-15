"""Optional full-pipeline evaluation; requires a user-provided Gemini API key."""
from __future__ import annotations
import json, sys
from pathlib import Path
from time import perf_counter
import pandas as pd
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT)); load_dotenv(ROOT/".env")
from schema_bridge.pipeline import run_mapping

def main():
    import os
    if not os.getenv("GEMINI_API_KEY"):
        raise SystemExit("Set GEMINI_API_KEY in .env first. This script makes live API requests and may use your account quota.")
    gold=json.loads((ROOT/"data/gold_mapping.json").read_text()); targets=json.loads((ROOT/"data/target_schema.json").read_text())["fields"]; dictionary=(ROOT/"data/data_dictionary.txt").read_text(); results=[]
    for dataset,key in [("LEGACY_POLICY","policy"),("LEGACY_CLAIM","claim"),("LEGACY_POLICY_V2","policy_v2")]:
        frame=pd.read_csv(ROOT/f"data/generated/{dataset}.csv"); expected=gold[key]; started=perf_counter(); mappings=run_mapping(frame,targets,dictionary,"Gemini"); top1=[]; top3=[]; accepted=[]; review=[]; errors=[]
        for item in mappings:
            truth=expected.get(item["source_field"],[None,"no_match"])[0]; decision=item["decision"]
            top1.append(decision.target_field==truth)
            names=[c["target"]["name"] for c in item["candidates"]]
            if truth is not None: top3.append(truth in names)
            if decision.target_field!=truth: errors.append({"source":item["source_field"],"expected":truth,"predicted":decision.target_field,"issues":item["verification"].issues})
            if item["status"]=="auto_accepted": accepted.append(decision.target_field==truth)
            else: review.append(item["source_field"])
        results.append({"dataset":dataset,"fields":len(mappings),"top1_mapping_accuracy":sum(top1)/len(top1),"top3_candidate_recall":sum(top3)/max(1,len(top3)),"rule_verifier_pass_rate":sum(x["verification"].passed for x in mappings)/len(mappings),"auto_accept_precision":sum(accepted)/len(accepted) if accepted else None,"auto_accepted":len(accepted),"human_review_share":len(review)/len(mappings),"seconds":round(perf_counter()-started,2),"tokens":sum(x["usage"].get("prompt_tokens",0)+x["usage"].get("response_tokens",0) for x in mappings),"repairs":sum(x["repair_count"] for x in mappings),"worst_errors":errors[:3]})
    (ROOT/"eval/gemini_results.json").write_text(json.dumps(results,indent=2),encoding="utf-8")
    text="# Gemini evaluation results\n\nSynthetic data only. This run used your configured model/API key; results do not establish carrier performance.\n\n"
    for r in results:
        precision=f"{r['auto_accept_precision']:.1%}" if r["auto_accept_precision"] is not None else "not measurable (none auto-accepted)"
        text+=f"## {r['dataset']}\n\n- Top-1 mapping accuracy: {r['top1_mapping_accuracy']:.1%}\n- Top-3 candidate recall: {r['top3_candidate_recall']:.1%}\n- Verifier pass rate: {r['rule_verifier_pass_rate']:.1%}\n- Auto-accept precision: {precision} ({r['auto_accepted']} auto-accepted)\n- Human-review share: {r['human_review_share']:.1%}\n- Runtime: {r['seconds']} seconds\n- Gemini tokens reported: {r['tokens']}\n- Repair attempts: {r['repairs']}\n\n"
        for e in r["worst_errors"]: text+=f"- Error: `{e['source']}` expected `{e['expected']}`, proposed `{e['predicted']}`, verifier issues: {e['issues']}\n"
        text+="\n"
    (ROOT/"eval/gemini_results.md").write_text(text,encoding="utf-8"); print(text)

if __name__=="__main__": main()
