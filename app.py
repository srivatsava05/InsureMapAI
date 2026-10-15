"""InsureMapAI interactive review workbench."""
from __future__ import annotations
import json, os, sys, csv, io
from pathlib import Path
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
load_dotenv(ROOT/".env",override=True)
from schema_bridge.pipeline import run_mapping
from schema_bridge.storage import save_decision, audit_rows
from schema_bridge.engine import sql_expression
from schema_bridge.passport import evidence_passport
from schema_bridge.schema import normalize_target_fields

st.set_page_config(page_title="InsureMapAI",page_icon="🔗",layout="wide")
st.markdown("""<style>
:root{--ink:#20384a;--muted:#526a79;--canvas:#f3f7f7;--card:#ffffff;--line:#d9e4e5;--teal:#167d82;--teal-dark:#11666b;--sidebar:#183b4a}
.stApp,[data-testid="stAppViewContainer"]{background:var(--canvas);color:var(--ink)}
.block-container{padding-top:1.6rem;max-width:1450px}
[data-testid="stHeader"]{background:transparent}
section[data-testid="stSidebar"]{background:var(--sidebar)}
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"],section[data-testid="stSidebar"] label,section[data-testid="stSidebar"] p,section[data-testid="stSidebar"] h1,section[data-testid="stSidebar"] h2,section[data-testid="stSidebar"] h3,section[data-testid="stSidebar"] [data-testid="stCaptionContainer"]{color:#f2f7f6!important}
.stApp h1,.stApp h2,.stApp h3,.stApp p,.stApp label,.stApp [data-testid="stMetricLabel"],.stApp [data-testid="stMetricValue"],.stApp [data-testid="stCaptionContainer"],.stApp [data-testid="stMarkdownContainer"]{color:var(--ink)}
[data-testid="stMetric"]{background:var(--card);border:1px solid var(--line);padding:16px;border-radius:14px;box-shadow:0 2px 10px rgba(28,57,68,.04)}
[data-testid="stMetricLabel"],.stApp [data-testid="stCaptionContainer"]{color:var(--muted)!important}
[data-testid="stMetricValue"]{color:var(--ink)!important}
[data-testid="stExpander"]{background:var(--card);border:1px solid var(--line);border-radius:12px}
[data-testid="stAlert"]{border-radius:12px}
.stButton>button,.stDownloadButton>button{background:var(--teal);color:#fff;border:1px solid var(--teal);border-radius:10px;font-weight:600}
.stButton>button:hover,.stDownloadButton>button:hover{background:var(--teal-dark);color:#fff;border-color:var(--teal-dark)}
.needs{background:#fff4d6;color:#76530b;padding:4px 10px;border-radius:8px;font-weight:600}
.ok{background:#e5f5ed;color:#14683f;padding:4px 10px;border-radius:8px;font-weight:600}
</style>""",unsafe_allow_html=True)

@st.cache_data
def read_targets(): return json.loads((ROOT/"data/target_schema.json").read_text(encoding="utf-8"))["fields"]

st.title("InsureMapAI")
st.caption("Legacy insurance data → evidence-backed, verified mappings → human approval")
st.info("Prototype uses synthetic data. Never upload policyholder or other confidential data to a consumer Gemini API.")

with st.sidebar:
    st.header("Project setup")
    gemini_key=os.getenv("GEMINI_API_KEY","").strip()
    st.markdown("### Mapping engine")
    st.markdown("**Gemini AI** · schema-grounded mapping")
    if gemini_key:
        st.success("Gemini API key detected. Mapping runs use Gemini.")
    else:
        st.warning("Gemini API key is empty. Add it to the project .env file before running mappings.")
    mongodb_uri=os.getenv("MONGODB_URI","").strip()
    if mongodb_uri:
        st.success("MongoDB connection URI detected. Reviews and audit events will be stored in MongoDB.")
    else:
        st.warning("MongoDB is not configured. Add your Atlas connection URI to MONGODB_URI in .env.")
    demo=st.selectbox("Synthetic dataset",["LEGACY_POLICY","LEGACY_CLAIM","LEGACY_POLICY_V2"])
    up=st.file_uploader("Or upload a CSV",type=["csv"])
    file_path=ROOT/f"data/generated/{demo}.csv"
    if up:
        try: frame=pd.read_csv(up)
        except Exception as e: st.error(f"Could not read CSV: {e}"); frame=pd.DataFrame()
    elif file_path.exists(): frame=pd.read_csv(file_path)
    else: frame=pd.DataFrame()
    dict_file=st.file_uploader("Optional dictionary (.txt)",type=["txt"])
    dictionary=dict_file.getvalue().decode("utf-8",errors="replace") if dict_file else (ROOT/"data/data_dictionary.txt").read_text(encoding="utf-8")
    target_up=st.file_uploader("Optional target schema (.json)",type=["json"])
    try:
        target_document=json.loads(target_up.getvalue().decode("utf-8")) if target_up else read_targets()
        targets=normalize_target_fields(target_document)
    except Exception as e:
        st.error(f"Invalid target schema: {e}"); targets=read_targets()
    if st.button("Generate synthetic data",use_container_width=True):
        import subprocess
        subprocess.run([sys.executable,str(ROOT/"data/generate_data.py")],check=True,cwd=ROOT)
        st.cache_data.clear(); st.rerun()
    run=st.button("Run Gemini mapping",type="primary",use_container_width=True,disabled=frame.empty or not gemini_key or not mongodb_uri)
    st.caption("Gemini proposes mappings and can repair verifier failures. Profiling, retrieval, transformations and verification run locally; reviewer decisions and audit history use MongoDB.")

if frame.empty:
    st.warning("Generate synthetic data from the sidebar or upload a CSV to begin.")
    st.stop()

profiles=[]
from schema_bridge.profile import profile_frame
profiles=profile_frame(frame)
c1,c2,c3=st.columns(3)
c1.metric("Rows",f"{len(frame):,}"); c2.metric("Source columns",len(frame.columns)); c3.metric("Null cells",f"{int(frame.isna().sum().sum()):,}")
with st.expander("Source preview and profile",expanded=False):
    st.dataframe(frame.head(8),use_container_width=True)
    st.dataframe(pd.DataFrame(profiles)[["name","type","null_rate","patterns","distinct"]],use_container_width=True,hide_index=True)

if run:
    try:
        with st.spinner("Profiling, retrieving evidence, proposing rules and verifying sample rows…"):
            st.session_state["results"]=run_mapping(frame,targets,dictionary,"Gemini")
            st.session_state["mode"]="Gemini"
    except Exception as e: st.error(str(e))

results=st.session_state.get("results",[])
if results:
    st.subheader("Mapping workbench")
    high=sum(r["status"]=="auto_accepted" for r in results); human=len(results)-high
    m1,m2,m3=st.columns(3); m1.metric("Proposed mappings",len(results)); m2.metric("High confidence + verified",high); m3.metric("Needs review",human)
    only_review=st.toggle("Show only needs-human items",value=False)
    rows=[r for r in results if not only_review or r["status"]!="auto_accepted"]
    overview=[]
    for r in rows:
        d=r["decision"]; v=r["verification"]
        overview.append({"Source field":r["source_field"],"Suggested target":d.target_field or "—","Rule":d.rule.type,"Confidence":r["confidence"],"Verifier":"Pass" if v.passed else "Review","Status":r["status"]})
    st.dataframe(pd.DataFrame(overview),use_container_width=True,hide_index=True,column_config={"Confidence":st.column_config.ProgressColumn("Confidence",min_value=0,max_value=1,format="%.2f")})
    choice=st.selectbox("Inspect a source column",[r["source_field"] for r in results])
    r=next(x for x in results if x["source_field"]==choice); d=r["decision"]; v=r["verification"]
    left,right=st.columns([1,1])
    with left:
        st.markdown(f"### `{r['source_field']}` → `{d.target_field or 'Unmapped'}`")
        st.write(d.reasoning)
        st.caption(f"Evidence: {d.evidence_quote or 'No exact dictionary quote supplied'}")
        st.markdown("**Retrieved target candidates**")
        st.dataframe(pd.DataFrame([{"Target":c["target"]["name"],"Entity":c["target"]["entity"],"Rank score":c["score"],"Name":c["name_similarity"],"Type":c["type_match"],"Pattern":c["pattern_match"]} for c in r["candidates"]]),use_container_width=True,hide_index=True)
    with right:
        st.markdown("**Rule and verifier**")
        st.json(d.rule.model_dump())
        st.markdown(f"Verifier: {'✅ Passed' if v.passed else '⚠️ Needs review'} · {v.pass_rate:.0%} values transformed")
        for issue in v.issues: st.warning(issue)
        st.dataframe(pd.DataFrame(v.preview),use_container_width=True,hide_index=True)
    st.divider()
    x1,x2,x3,x4=st.columns([1,1,1,2])
    with x1:
        if st.button("Approve mapping",disabled=not d.target_field):
            try:
                save_decision(r["source_field"],d.target_field,d.rule.model_dump(),"approved","Approved in review workbench")
                st.success("Approval and audit event saved to MongoDB.")
            except Exception as e: st.error(f"Could not save approval to MongoDB: {e}")
    with x2:
        if st.button("Reject mapping"):
            try:
                save_decision(r["source_field"],None,d.rule.model_dump(),"rejected","Rejected in review workbench")
                st.warning("Rejection logged in MongoDB.")
            except Exception as e: st.error(f"Could not save rejection to MongoDB: {e}")
    target_names=[t["name"] for t in targets]
    with x4:
        corrected=st.selectbox("Correct target and save feedback",target_names,index=target_names.index(d.target_field) if d.target_field in target_names else 0,key="correct_target")
    from schema_bridge.models import Rule
    rule_json=st.text_area("Edit transformation rule JSON (allowlisted rule names only)",value=json.dumps(d.rule.model_dump(),indent=2),height=120)
    if st.button("Save correction as feedback"):
        try:
            edited_rule=Rule.model_validate_json(rule_json)
            save_decision(r["source_field"],corrected,edited_rule.model_dump(),"edited","Reviewer correction; reusable feedback")
            st.success("Target and rule correction stored and available to later retrieval runs.")
        except Exception as e: st.error(f"Invalid rule JSON: {e}")

    st.subheader("Validation, metrics and exports")
    st.caption("Gemini generated these mapping proposals. Rule execution and validation are deterministic local checks, not model self-reports.")
    flat=[]; trace=[]; sql=[]
    for r in results:
        d=r["decision"]; v=r["verification"]
        flat.append({"source_field":r["source_field"],"target_field":d.target_field,"rule_type":d.rule.type,"rule_params":json.dumps(d.rule.params),"confidence":r["confidence"],"status":r["status"],"verified":v.passed,"issues":"; ".join(v.issues),"evidence":d.evidence_quote,"reasoning":d.reasoning})
        passport=evidence_passport(frame,targets,dictionary,r)
        trace.append({**passport,"trace_id":f"{demo}:{r['source_field']}","confidence":r["confidence"],"reviewer":"pending"})
        if d.target_field: sql.append(f"-- {r['source_field']} -> {d.target_field}\n{sql_expression(r['source_field'],d.rule)} AS \"{d.target_field}\"")
    csv_bytes=pd.DataFrame(flat).to_csv(index=False).encode(); trace_bytes=json.dumps(trace,indent=2).encode()
    py_rules=[{"source":item["source_field"],"target":item["decision"].target_field,"rule":item["decision"].rule.model_dump()} for item in results if item["decision"].target_field and item["decision"].rule.type!="CUSTOM"]
    py_payload=json.dumps(py_rules,ensure_ascii=False)
    python_script=f'''"""Generated by InsureMapAI. Review the mapping before using on any real data."""
import json
import pandas as pd
from schema_bridge.engine import transform_series
from schema_bridge.models import Rule

RULES = json.loads({py_payload!r})
source = pd.read_csv("input.csv")
output = pd.DataFrame(index=source.index)
for item in RULES:
    if item["source"] not in source.columns:
        raise KeyError(f"Missing source field: {{item['source']}}")
    output[item["target"]] = transform_series(source[item["source"]], Rule.model_validate(item["rule"]))
output.to_csv("transformed_output.csv", index=False)
'''
    validation_md="# InsureMapAI validation report\n\nSynthetic or user-selected sample only; review each issue before use.\n\n"+"\n".join(f"- **{r['source_field']} → {r['decision'].target_field or 'no match'}:** {'PASS' if r['verification'].passed else 'REVIEW'} ({r['verification'].pass_rate:.0%} transformed)"+("; " + "; ".join(r['verification'].issues) if r['verification'].issues else "") for r in results)
    a,b,c,dcol=st.columns(4)
    a.download_button("Download mapping specification CSV",csv_bytes,"mapping_spec.csv","text/csv")
    b.download_button("Download traceability JSON",trace_bytes,"traceability_matrix.json","application/json")
    c.download_button("Download SQL expressions",("\n\n".join(sql)).encode(),"transform.sql","text/plain")
    dcol.download_button("Download Python transform",python_script.encode(),"transform.py","text/x-python")
    st.download_button("Download validation report",validation_md.encode(),"validation_report.md","text/markdown")
    token_in=sum(r["usage"].get("prompt_tokens",0) for r in results); token_out=sum(r["usage"].get("response_tokens",0) for r in results)
    st.caption(f"Observed Gemini token counts for this run: {token_in:,} input · {token_out:,} output. Check your current account quota and pricing before production use.")

with st.expander("Recent audit log",expanded=False):
    try:
        audit=audit_rows(); st.dataframe(pd.DataFrame(audit),use_container_width=True,hide_index=True) if audit else st.caption("No review decisions yet.")
    except Exception as e: st.warning(f"MongoDB audit log unavailable: {e}")

st.caption("InsureMapAI · synthetic-data prototype")
