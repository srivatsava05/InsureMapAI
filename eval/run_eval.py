"""Evaluate the local heuristic baseline on the included synthetic gold set."""
from __future__ import annotations
import json, sys
from pathlib import Path
from time import perf_counter
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from schema_bridge.profile import profile_frame
from schema_bridge.candidates import rank_candidates
from schema_bridge.pipeline import heuristic_decision
from schema_bridge.verify import verify_rule

def key_for(dataset): return "claim" if dataset=="LEGACY_CLAIM" else "policy_v2" if dataset.endswith("V2") else "policy"

def main():
    gold=json.loads((ROOT/"data/gold_mapping.json").read_text()); targets=json.loads((ROOT/"data/target_schema.json").read_text())["fields"]; dictionary=(ROOT/"data/data_dictionary.txt").read_text(); rows=[]
    for ds in ["LEGACY_POLICY","LEGACY_CLAIM","LEGACY_POLICY_V2"]:
        started=perf_counter(); frame=pd.read_csv(ROOT/f"data/generated/{ds}.csv"); expected=gold[key_for(ds)]; top1=[]; top3=[]; valid=[]; accepted_correct=[]; accepted_count=0; human=[]; errors=[]
        for profile in profile_frame(frame):
            cand=rank_candidates(profile,targets,dictionary); pred=heuristic_decision(profile,cand); truth=expected.get(profile["name"],[None,"no_match"])[0]
            top1.append(pred.target_field==truth)
            if pred.target_field!=truth: errors.append({"source":profile["name"],"expected":truth,"predicted":pred.target_field,"top_candidates":[x["target"]["name"] for x in cand[:3]]})
            candidates=[x["target"]["name"] for x in cand[:3]]
            if truth is not None: top3.append(truth in candidates)
            target=next((t for t in targets if t["name"]==pred.target_field),{}); v=verify_rule(frame[profile["name"]],pred.rule,target,profile["type"]); valid.append(v.passed)
            conf=min(1,.55*(cand[0]["score"] if cand else 0)+.2*float(bool(cand and pred.target_field==cand[0]["target"]["name"]))+.25*float(v.passed))
            is_accepted=conf>=.85 and v.passed and pred.decision=="mapped" and pred.rule.type!="CUSTOM"
            accepted_count+=int(is_accepted); accepted_correct.append(is_accepted and pred.target_field==truth); human.append(not is_accepted)
        rows.append({"dataset":ds,"fields":len(frame.columns),"top1_mapping_accuracy":round(sum(top1)/len(top1),3),"top3_candidate_recall":round(sum(top3)/max(1,len(top3)),3),"rule_verifier_pass_rate":round(sum(valid)/len(valid),3),"auto_accept_precision":round(sum(accepted_correct)/accepted_count,3) if accepted_count else None,"auto_accepted":accepted_count,"human_review_share":round(sum(human)/len(human),3),"seconds_local":round(perf_counter()-started,3),"tokens":0,"worst_errors":errors[:3]})
    # Simulated reviewer corrections derived from hand-authored gold. This is explicitly an upper bound.
    frame=pd.read_csv(ROOT/"data/generated/LEGACY_POLICY_V2.csv"); truth_v2=gold["policy_v2"]; memory=[{"source_name":name,"target_field":target} for name,(target,_) in gold["policy"].items() if target]; no_feedback=[]; with_feedback=[]; transitions=[]
    for profile in profile_frame(frame):
        truth=truth_v2.get(profile["name"],[None,"no_match"])[0]
        pred_without=heuristic_decision(profile,rank_candidates(profile,targets,dictionary,[])).target_field
        pred_with=heuristic_decision(profile,rank_candidates(profile,targets,dictionary,memory)).target_field
        no_feedback.append(pred_without==truth); with_feedback.append(pred_with==truth)
        transitions.append({"source":profile["name"],"truth":truth,"without_feedback":pred_without,"with_feedback":pred_with,"transition":"corrected" if pred_without!=truth and pred_with==truth else "regressed" if pred_without==truth and pred_with!=truth else "unchanged"})
    feedback={"donor_dataset":"LEGACY_POLICY","held_out_variant":"LEGACY_POLICY_V2","held_out_fields":len(frame.columns),"v2_top1_without_feedback":round(sum(no_feedback)/len(no_feedback),3),"v2_top1_with_simulated_policy_feedback":round(sum(with_feedback)/len(with_feedback),3),"corrected_errors":sum(x["transition"]=="corrected" for x in transitions),"regressions":sum(x["transition"]=="regressed" for x in transitions),"note":"Ablation transfers simulated corrections from hand-authored policy gold to a renamed variant. The variant shares the synthetic generator and semantics, so this is not an independent test or a real reviewer experiment.","transitions":transitions}
    result={"label":"Synthetic data only; heuristic preview baseline, not Gemini performance or carrier validation.","runs":rows,"feedback_comparison":feedback}
    (ROOT/"eval/results.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    md="# Synthetic baseline results\n\n> These results use hand-authored synthetic examples and the local heuristic preview. They are not Gemini results or evidence of carrier performance.\n\n"
    for r in rows:
        precision=f"{r['auto_accept_precision']:.1%}" if r["auto_accept_precision"] is not None else "not measurable (no auto-accepted mappings)"
        md+=f"## {r['dataset']}\n\n- Columns: {r['fields']}\n- Top-1 mapping accuracy: {r['top1_mapping_accuracy']:.1%}\n- Top-3 candidate recall: {r['top3_candidate_recall']:.1%}\n- Rule verifier pass rate: {r['rule_verifier_pass_rate']:.1%}\n- Auto-accept precision: {precision} ({r['auto_accepted']} auto-accepted mappings)\n- Human-review share: {r['human_review_share']:.1%}\n- Local evaluation runtime: {r['seconds_local']} seconds; tokens: {r['tokens']} (no Gemini calls)\n\n### Example mismatches\n\n"
        for e in r["worst_errors"]: md+=f"- `{e['source']}` expected `{e['expected']}` but suggested `{e['predicted']}`; top candidates: {', '.join(map(str,e['top_candidates']))}.\n"
        md+="\n"
    md+=f"## Cross-schema feedback ablation\n\n- Donor: `{feedback['donor_dataset']}` hand-authored mapping corrections; evaluation variant: `{feedback['held_out_variant']}` ({feedback['held_out_fields']} renamed fields).\n- Top-1 without feedback: {feedback['v2_top1_without_feedback']:.1%}; with feedback: {feedback['v2_top1_with_simulated_policy_feedback']:.1%}.\n- Wrong-to-correct transitions: {feedback['corrected_errors']}; correct-to-wrong regressions: {feedback['regressions']}.\n- This is an oracle-style simulated feedback ablation, not a live reviewer study. The renamed variant shares the data generator and semantics, so it is not independent generalization evidence. See `feedback_comparison.transitions` in `results.json` for field-level outcomes.\n\n## Interpretation\n\nThis is a small synthetic heuristic baseline, not an independent benchmark or Gemini performance result. The gold file is hand-written and the V2 data shares the same synthetic process. Low precision/coverage means suggestions must remain in human review.\n"
    (ROOT/"eval/results.md").write_text(md,encoding="utf-8"); print(md)

if __name__=="__main__": main()
