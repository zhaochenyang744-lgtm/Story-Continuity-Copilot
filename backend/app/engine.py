from __future__ import annotations
from typing import Any
from .provider import ProviderFailure, ProviderInvalidJson, ProviderPort, ProviderTimeout, ProviderUnavailable

ALLOWED_STATUS={"conflict","insufficient_evidence"}
ALLOWED_CATEGORY={"attribute","location_action","timeline","character_knowledge","object_state","relationship","world_rule","event_status"}
ALLOWED_SEVERITY={"low","medium","high"}
ALLOWED_MEMORY_TYPE={"static_canon","dynamic_state","event_timeline","character_knowledge","open_thread"}
MAX_RUN_TOKENS=8000
PROMPT_VERSION="continuity-review-v4"
class ContinuityEngine:
    def __init__(self,provider:ProviderPort): self.provider=provider
    def provenance(self)->dict[str,str]:
        return {"provider_label":self.provider.label,"model_label":getattr(self.provider,"model_label",self.provider.label),"prompt_version":PROMPT_VERSION,"schema_version":"continuity-issue-v3","retrieval_method_version":"demo-retrieval-v2"}
    def execute(self,data:dict[str,Any])->dict[str,Any]:
        if not self.provider.available:return {"status":"failed","error_code":"provider_unavailable","retryable":True}
        try:r=self.provider.evaluate({"draft":data["draft"],"claims":data["claims"],"memory":data["memory"],"output_schema":{"issues":[{"claim_span_id":"current claim id","status":"conflict|insufficient_evidence","category":"allowed category","severity":"low|medium|high","explanation":"non-empty short reviewable conclusion","evidence":[{"chapter_id":"allowed chapter id","span_id":"allowed span id","relation":"supports|contradicts|context","sufficiency":"sufficient|insufficient","related_memory_ids":["known memory id"]}],"proposed_memory_change":{"operation":"add|replace","memory_type":"allowed memory type","subject":"string","predicate":"string","value":"string","affected_memory_id":"required for replace only"}}]}})
        except ProviderUnavailable:return {"status":"failed","error_code":"provider_unavailable","retryable":True}
        except ProviderTimeout:return {"status":"timed_out","error_code":"provider_timeout","retryable":True}
        except ProviderInvalidJson:return {"status":"failed","error_code":"invalid_json","retryable":True}
        except ProviderFailure:return {"status":"failed","error_code":"provider_error","retryable":True}
        if (r.input_tokens or 0)+(r.output_tokens or 0)>MAX_RUN_TOKENS:return {"status":"budget_paused","error_code":"budget_paused","retryable":True,"input_tokens":r.input_tokens,"output_tokens":r.output_tokens,"latency_ms":r.latency_ms}
        try:issues=self.validate(r.payload,data)
        except ValueError as e:return {"status":"failed","error_code":str(e),"retryable":True,"input_tokens":r.input_tokens,"output_tokens":r.output_tokens,"latency_ms":r.latency_ms}
        return {"status":"completed","issues":issues,"input_tokens":r.input_tokens,"output_tokens":r.output_tokens,"latency_ms":r.latency_ms,"cost_cny":r.cost_cny}
    def validate(self,payload:Any,data:dict[str,Any]):
        if not isinstance(payload,dict) or set(payload)!={"issues"} or not isinstance(payload.get("issues"),list):raise ValueError("schema_invalid")
        claims={x["id"]:x for x in data["claims"]}; mem={x["id"]:x for x in data["memory"]}; output=[]
        for raw in payload["issues"]:
            if raw.get("status")=="no_conflict":raise ValueError("no_conflict_issue_forbidden")
            explanation=raw.get("explanation") if isinstance(raw,dict) else None
            if not isinstance(raw,dict) or raw.get("claim_span_id") not in claims or raw.get("status") not in ALLOWED_STATUS or raw.get("category") not in ALLOWED_CATEGORY or raw.get("severity") not in ALLOWED_SEVERITY or not isinstance(explanation,str) or not explanation.strip():raise ValueError("schema_invalid")
            evs=raw.get("evidence",[]); allowed={x["id"]:x for x in claims[raw["claim_span_id"]]["allowed_evidence"]}
            if raw["status"]=="conflict" and not evs:raise ValueError("conflict_without_evidence")
            if raw["status"]=="insufficient_evidence" and evs:raise ValueError("insufficient_evidence_upgraded")
            if raw["status"]=="insufficient_evidence" and raw.get("proposed_memory_change") is not None:raise ValueError("insufficient_evidence_memory_change")
            cleaned=[]
            for ev in evs:
                if not isinstance(ev,dict) or ev.get("span_id") not in allowed:raise ValueError("evidence_unresolvable")
                s=allowed[ev["span_id"]]
                if ev.get("chapter_id")!=s["chapter_id"] or ev.get("relation") not in {"supports","contradicts","context"} or ev.get("sufficiency") not in {"sufficient","insufficient"} or not set(ev.get("related_memory_ids",[]))<=set(mem):raise ValueError("evidence_unresolvable")
                if raw["status"]=="conflict" and (ev.get("relation")!="contradicts" or ev.get("sufficiency")!="sufficient"):raise ValueError("conflict_evidence_not_direct")
                cleaned.append({"chapter_id":s["chapter_id"],"span_id":s["id"],"excerpt":s["body"],"relation":ev["relation"],"sufficiency":ev["sufficiency"],"related_memory_ids":ev.get("related_memory_ids",[])})
            change=raw.get("proposed_memory_change")
            if change is not None:
                required={"memory_type","subject","predicate","value","operation"}
                if (not isinstance(change,dict) or not required<=set(change)
                    or change["memory_type"] not in ALLOWED_MEMORY_TYPE
                    or change["operation"] not in {"add","replace"}
                    or any(not isinstance(change[key],str) or not change[key].strip() for key in ("subject","predicate","value"))
                    or (change["operation"]=="add" and change.get("affected_memory_id") is not None)
                    or (change["operation"]=="replace" and change.get("affected_memory_id") not in mem)
                    or raw["status"]!="conflict"):
                    raise ValueError("schema_invalid")
            output.append({"claim_span_id":raw["claim_span_id"],"status":raw["status"],"category":raw["category"],"severity":raw["severity"],"evidence_status":"sufficient" if evs else "insufficient","explanation":explanation.strip()[:500],"evidence":cleaned,"proposed_memory_change":change})
        return output
