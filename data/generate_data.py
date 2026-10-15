"""Create reproducible, deliberately imperfect synthetic insurance migration data."""
from __future__ import annotations
import csv, json, random
from datetime import date, timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parent
OUT=ROOT/"generated"
random.seed(2606)
STATUSES=["A","C","X","P","Z"] # Z is intentionally unmapped
STATES=["CA","TX","NY","WA","IL"]
LOB=["AUTO","HOME","PROP"]

def write_csv(name, rows):
    with (OUT/name).open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

def dirty(v, chance=.05): return None if random.random()<chance else v

def policy_rows(n=300, variant=False):
    rows=[]
    for i in range(1,n+1):
        eff=date(2024,1,1)+timedelta(days=random.randrange(600)); exp=eff+timedelta(days=365)
        stat=STATUSES[4] if i==n else random.choice(STATUSES[:4])
        first=random.choice(["Asha","Noah","Mina","Arjun","Ivy","Sam"]); last=random.choice(["Rao","Shah","Chen","Patel","Kim"])
        phone=f"({random.randrange(200,999)}) {random.randrange(200,999)}-{random.randrange(1000,9999)}"
        zip5=f"{random.randrange(10000,99999)}"
        base={"POL_NO":f"P-{i:06d}","INS_NM":f"{last}, {first}","EFF_DT":eff.strftime("%m%d%Y") if i%2 else eff.strftime("%y%m%d"),"EXP_DT":exp.strftime("%m/%d/%Y"),"PREM_AMT":random.randrange(80000,850000),"STAT_CD":stat,"LOB_CD":random.choice(LOB),"AGT_ID":f"AG{random.randrange(100,150)}","ST":random.choice(STATES),"ZIP5":zip5,"ZIP4":f"{random.randrange(1000,9999)}","PHONE":phone,"EMAIL":f"{first.lower()}.{last.lower()}{i}@example.test","ADDR1":f"{random.randrange(10,9999)} Main St","CITY":random.choice(["Austin","Irvine","Buffalo","Seattle"]),"DEDUCT_AMT":random.randrange(50000,200000),"LIMIT_AMT":random.randrange(1000000,5000000),"COV_CD":random.choice(["COLL","LIAB","COMP"]),"VEH_YR":random.randrange(2005,2026),"VIN":f"SYN{i:014d}","RENEW_FLG":random.choice(["Y","N"]),"CR_DT":(eff-timedelta(days=14)).strftime("%Y-%m-%d"),"CANCEL_DT":"" if stat!="C" else eff.strftime("%m%d%Y"),"AGENCY_NM":random.choice(["Northstar Agency","Cedar Mutual","Harbor Group"]),"SRC_SYS":random.choice(["AS400","POLIS","LEGACY1"])}
        # Insert a handful of invalid dates and nulls, but retain syntactically parseable core identity fields.
        if i in (17,111): base["EFF_DT"]="02312024"
        for col in list(base):
            if col not in ("POL_NO","EFF_DT","STAT_CD") and random.random()<.035: base[col]=None
        if variant:
            rename={"POL_NO":"contract_key","INS_NM":"customer_label","EFF_DT":"start_on","EXP_DT":"end_on","PREM_AMT":"written_premium_minor","STAT_CD":"lifecycle","LOB_CD":"product_family","AGT_ID":"producer_ref","ST":"risk_state","ZIP5":"postal_primary","ZIP4":"postal_suffix","PHONE":"contact_tel","EMAIL":"contact_mail","ADDR1":"street_line","CITY":"municipality","DEDUCT_AMT":"deductible_minor","LIMIT_AMT":"coverage_limit_minor","COV_CD":"coverage_kind","VEH_YR":"model_year","VIN":"asset_ref","RENEW_FLG":"renewal_indicator","CR_DT":"created_on","CANCEL_DT":"terminated_on","AGENCY_NM":"producer_org","SRC_SYS":"origin_platform"}
            base={rename[k]:v for k,v in base.items()}
        rows.append(base)
    return rows

def claim_rows(n=200):
    rows=[]
    policies=300
    for i in range(1,n+1):
        loss=date(2024,1,1)+timedelta(days=random.randrange(700)); rpt=loss+timedelta(days=random.randrange(25))
        r={"CLM_NO":f"C-{i:06d}","POL_NO":f"P-{random.randrange(1,policies+1):06d}","LOSS_DT":loss.strftime("%Y%m%d") if i%2 else loss.strftime("%m/%d/%Y"),"RPT_DT":rpt.strftime("%m%d%Y"),"CLM_STAT":random.choice(["O","C","R"]),"RSV_AMT":random.randrange(10000,1000000),"PAID_AMT":random.randrange(0,500000),"CAUSE_CD":random.choice(["COLLISION","WATER","FIRE","THEFT"]),"ADJ_ID":f"AD{random.randrange(10,60)}","LOSS_ST":random.choice(STATES),"INJURY_FLG":random.choice(["Y","N"]),"CLOSED_DT":"" if i%4 else rpt.strftime("%Y-%m-%d"),"EXPENSE_AMT":random.randrange(0,100000),"RECOVERY_AMT":random.randrange(0,150000),"SRC_SYS":random.choice(["AS400","CLAIMS1"])}
        if i in (29,147): r["LOSS_DT"]="not-a-date"
        for col in list(r):
            if col not in ("CLM_NO","POL_NO") and random.random()<.04: r[col]=None
        rows.append(r)
    return rows

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    p=policy_rows(); c=claim_rows(); p2=policy_rows(300,True)
    write_csv("LEGACY_POLICY.csv",p); write_csv("LEGACY_CLAIM.csv",c); write_csv("LEGACY_POLICY_V2.csv",p2)
    schema={"label":"Synthetic simplified insurance target schema; not a real vendor schema.","fields":[]}
    definitions={"policy":[("policy_number","string",True,"Unique contract identifier",[]),("effective_date","date",True,"Coverage start date",[]),("expiration_date","date",True,"Coverage end date",[]),("premium_amount","number",False,"Written premium in currency units",[]),("policy_status","string",True,"Policy lifecycle status",["active","cancelled","expired","pending"]),("line_of_business","string",False,"Insurance product family",["auto","home","property"]),("producer_id","string",False,"Producing agent reference",[]),("risk_state","string",False,"Two-letter risk state",STATES),("postal_code","string",False,"Five-digit postal code",[])],"insured":[("full_name","string",False,"Named insured full name",[]),("first_name","string",False,"Insured first name",[]),("last_name","string",False,"Insured family name",[]),("phone","string",False,"Contact telephone number",[]),("email","string",False,"Contact email",[]),("street_address","string",False,"Primary street address",[]),("city","string",False,"Mailing city",[])],"coverage":[("deductible_amount","number",False,"Coverage deductible in currency units",[]),("limit_amount","number",False,"Coverage limit in currency units",[]),("coverage_type","string",False,"Coverage kind",["collision","liability","comprehensive"]),("vehicle_year","integer",False,"Model year for insured auto",[]),("vehicle_id","string",False,"Vehicle identification value",[]),("renewal_flag","boolean",False,"Whether policy is a renewal",[])],"claim":[("claim_number","string",True,"Unique claim identifier",[]),("policy_number","string",True,"Related policy identifier",[]),("loss_date","date",True,"Date of insured loss",[]),("reported_date","date",False,"Date claim was reported",[]),("claim_status","string",False,"Claim lifecycle status",["open","closed","reopened"]),("reserve_amount","number",False,"Current loss reserve in currency units",[]),("paid_amount","number",False,"Amount paid in currency units",[]),("cause_code","string",False,"Reported cause of loss",[]),("adjuster_id","string",False,"Assigned adjuster reference",[]),("loss_state","string",False,"State where loss occurred",STATES),("injury_flag","boolean",False,"Whether injury is reported",[]),("closed_date","date",False,"Claim closure date",[]),("expense_amount","number",False,"Claim expense amount",[]),("recovery_amount","number",False,"Recovery/subrogation amount",[])]}
    for entity,fields in definitions.items():
        for name,typ,required,description,allowed in fields:
            schema["fields"].append({"entity":entity,"name":name,"type":typ,"required":required,"description":description,"allowed_values":allowed})
    (ROOT/"target_schema.json").write_text(json.dumps(schema,indent=2),encoding="utf-8")
    dictionary="""Synthetic training dictionary for legacy export columns (illustrative; not carrier documentation).\nPOL_NO: policy identifier assigned by the source policy system.\nINS_NM: insured name stored as LAST, FIRST.\nEFF_DT: policy effective date; mixed MMDDYYYY and YYMMDD strings.\nEXP_DT: policy expiration date.\nPREM_AMT: written premium stored as integer cents.\nSTAT_CD: A active, C cancelled, X expired, P pending; Z is a deliberate unknown.\nLOB_CD: AUTO, HOME or PROP product family.\nAGT_ID: producer identifier.\nST: two-character insured risk state.\nZIP5: primary five digit postal code.\nZIP4: optional postal suffix.\nPHONE: insured telephone, mixed punctuation.\nEMAIL: insured email address.\nADDR1: insured street address.\nCITY: mailing city.\nDEDUCT_AMT: deductible stored in cents.\nLIMIT_AMT: limit stored in cents.\nCOV_CD: COLL collision, LIAB liability, COMP comprehensive.\nVEH_YR: insured vehicle model year.\nVIN: synthetic vehicle identifier.\nRENEW_FLG: Y renewal, N new business.\nCR_DT: source row creation date, ISO format.\nCANCEL_DT: cancellation date, blank when not cancelled.\nCLM_NO: claim number.\nLOSS_DT: loss date; mixed YYYYMMDD and MM/DD/YYYY.\nRPT_DT: date claim was reported, MMDDYYYY.\nCLM_STAT: O open, C closed, R reopened.\nRSV_AMT: current reserve in cents.\nPAID_AMT: indemnity paid in cents.\n"""
    (ROOT/"data_dictionary.txt").write_text(dictionary,encoding="utf-8")
    # Gold definitions: explicit, human-authored mapping for supported tables, including unstructured fields.
    policy_map={"POL_NO":["policy_number","COPY"],"INS_NM":["full_name","COPY"],"EFF_DT":["effective_date","DATE_PARSE"],"EXP_DT":["expiration_date","DATE_PARSE"],"PREM_AMT":["premium_amount","NUMERIC_SCALE"],"STAT_CD":["policy_status","LOOKUP"],"LOB_CD":["line_of_business","LOOKUP"],"AGT_ID":["producer_id","COPY"],"ST":["risk_state","TRIM_CASE"],"ZIP5":["postal_code","COPY"],"ZIP4":[None,"no_match"],"PHONE":["phone","COPY"],"EMAIL":["email","TRIM_CASE"],"ADDR1":["street_address","COPY"],"CITY":["city","COPY"],"DEDUCT_AMT":["deductible_amount","NUMERIC_SCALE"],"LIMIT_AMT":["limit_amount","NUMERIC_SCALE"],"COV_CD":["coverage_type","LOOKUP"],"VEH_YR":["vehicle_year","CAST"],"VIN":["vehicle_id","COPY"],"RENEW_FLG":["renewal_flag","LOOKUP"],"CR_DT":[None,"no_match"],"CANCEL_DT":[None,"no_match"],"AGENCY_NM":[None,"no_match"],"SRC_SYS":[None,"no_match"]}
    claim_map={"CLM_NO":["claim_number","COPY"],"POL_NO":["policy_number","COPY"],"LOSS_DT":["loss_date","DATE_PARSE"],"RPT_DT":["reported_date","DATE_PARSE"],"CLM_STAT":["claim_status","LOOKUP"],"RSV_AMT":["reserve_amount","NUMERIC_SCALE"],"PAID_AMT":["paid_amount","NUMERIC_SCALE"],"CAUSE_CD":["cause_code","COPY"],"ADJ_ID":["adjuster_id","COPY"],"LOSS_ST":["loss_state","TRIM_CASE"],"INJURY_FLG":["injury_flag","LOOKUP"],"CLOSED_DT":["closed_date","DATE_PARSE"],"EXPENSE_AMT":["expense_amount","NUMERIC_SCALE"],"RECOVERY_AMT":["recovery_amount","NUMERIC_SCALE"],"SRC_SYS":[None,"no_match"]}
    rename={"POL_NO":"contract_key","INS_NM":"customer_label","EFF_DT":"start_on","EXP_DT":"end_on","PREM_AMT":"written_premium_minor","STAT_CD":"lifecycle","LOB_CD":"product_family","AGT_ID":"producer_ref","ST":"risk_state","ZIP5":"postal_primary","ZIP4":"postal_suffix","PHONE":"contact_tel","EMAIL":"contact_mail","ADDR1":"street_line","CITY":"municipality","DEDUCT_AMT":"deductible_minor","LIMIT_AMT":"coverage_limit_minor","COV_CD":"coverage_kind","VEH_YR":"model_year","VIN":"asset_ref","RENEW_FLG":"renewal_indicator","CR_DT":"created_on","CANCEL_DT":"terminated_on","AGENCY_NM":"producer_org","SRC_SYS":"origin_platform"}
    gold={"label":"Hand-authored synthetic ground truth; some low-value source fields intentionally have no target.","policy":policy_map,"claim":claim_map,"policy_v2":{rename[k]:v for k,v in policy_map.items()}}
    (ROOT/"gold_mapping.json").write_text(json.dumps(gold,indent=2),encoding="utf-8")
    print(f"Generated {len(p)} policy rows, {len(c)} claim rows, {len(p2)} policy V2 rows; all data synthetic.")
    print("Policy preview:"); print(p[:5])

if __name__=="__main__": main()
