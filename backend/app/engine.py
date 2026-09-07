from __future__ import annotations

import re
from typing import Any

from .memory_contract import CONTROLLED_PREDICATES
from .provider import InputBudgetExceeded, MAX_INPUT_BUDGET_UNITS, MAX_MEMORY_CANDIDATES_PER_BATCH, MEMORY_BATCH_TARGET_BUDGET_UNITS, ProviderFailure, ProviderInvalidJson, ProviderPort, ProviderTimeout, ProviderUnavailable, request_prompt_and_budget

ALLOWED_STATUS={"conflict","insufficient_evidence"}
ALLOWED_CATEGORY={"attribute","location_action","timeline","character_knowledge","object_state","relationship","world_rule","event_status"}
ALLOWED_SEVERITY={"low","medium","high"}
ALLOWED_MEMORY_TYPE={"static_canon","dynamic_state","event_timeline","character_knowledge","open_thread"}
REVIEW_NATURES={"confirmed_conflict","possible_conflict","state_change","insufficient_evidence"}
REVIEW_ACTIONS={"edit","apply_suggestion","keep_intentional","false_positive"}
EVIDENCE_CHAIN_ROLES={"prior_state","current_context","missing_link"}
MAX_RUN_TOKENS=8000
PROMPT_VERSION="continuity-review-v13-conservative-postrepair"
MEMORY_PROMPT_VERSION="memory-initialization-v9-field-contract"
RETRIEVAL_METHOD_VERSION="bounded-lexical-v4-longform"
RELATED_MEMORY_LIMIT=15
CONTINUITY_EVIDENCE_LIMIT=3
CONTINUITY_EVIDENCE_EXCERPT_CODEPOINTS=500
MEMORY_DELTA_RELATED_MEMORY_LIMIT=20
MEMORY_DELTA_SOURCE_LIMIT=12
MEMORY_DELTA_SOURCE_EXCERPT_CODEPOINTS=1600
SOURCE_CHUNK_METHOD_VERSION="source-chunk-v4-5800"
MAX_CHUNK_OVERLAP_CODEPOINTS=200
MEMORY_SCHEMA_REPAIR_MAX_ATTEMPTS=5
MEMORY_SCHEMA_REPAIR_MAX_PER_BATCH=2
MEMORY_CANDIDATE_FIELDS=("memory_type","subject","predicate","value","chapter_id","source_span_id")
MEMORY_DELTA_CANDIDATE_FIELDS=("change_kind","affected_memory_id","memory_type","subject","predicate","value","invalidation_reason","chapter_id","source_span_id")
MEMORY_REPAIRABLE_ERRORS={"top_level_shape_invalid","candidate_collection_invalid","candidate_count_invalid","empty_candidates","candidate_fields_invalid","memory_type_invalid","required_field_type_invalid","required_field_blank","candidate_length_invalid","evidence_unresolvable"}
ANALYSIS_RETRIEVAL_METHOD_VERSION="writing-analysis-lexical-v2-draft-claims"
CONTEXT_BRIEF_PROMPT_VERSION="context-brief-v4-deterministic-summary-coverage"
PLAN_ALIGNMENT_PROMPT_VERSION="plan-alignment-v3-event-language"
CHANGE_IMPACT_PROMPT_VERSION="change-impact-v1-layered"
STORY_QA_PROMPT_VERSION="story-qa-v1-bounded-layers"
FORESHADOW_SCAN_PROMPT_VERSION="foreshadow-scan-v6-background-location-isolation"
REVISION_PLAN_PROMPT_VERSION="revision-plan-v1-selected-issues"
AUTHOR_MATERIAL_COMPARISON_PROMPT_VERSION="author-material-comparison-v1-bound-snapshots"
CHANGE_IMPACT_INSUFFICIENT_SUMMARY="当前证据不足以支持影响结论。"
STORY_QA_INSUFFICIENT_ANSWER="当前证据不足以回答这个问题。"
FORESHADOW_INSUFFICIENT_SUMMARY="当前未发现有可采信已写证据的伏笔候选。"
PLAN_ALIGNMENT_STATUSES={"planned_covered","planned_missing","planned_early","planned_changed","insufficient_evidence"}
CONTEXT_BRIEF_SECTIONS={"related_plan","confirmed_fact","character_state","world_rule","open_thread","recent_source"}
STORY_QA_STATUSES={"answered","partial","insufficient","conflicting"}
STORY_QA_LAYERS={"confirmed","written","planned"}
REVISION_TASK_PRIORITIES={"high","medium","low"}


class MemoryCandidateValidationError(ValueError):
    """A redacted validation failure with only allowlisted structural context."""
    def __init__(self, code: str, *, field: str | None = None, candidate_ordinal: int | None = None):
        super().__init__(code)
        self.code=code
        self.field=field if field in MEMORY_CANDIDATE_FIELDS else None
        self.candidate_ordinal=candidate_ordinal if isinstance(candidate_ordinal,int) and candidate_ordinal>=1 else None

    def safe_context(self)->dict[str,Any]:
        context={}
        if self.field is not None:context["invalid_field"]=self.field
        if self.candidate_ordinal is not None:context["invalid_candidate_ordinal"]=self.candidate_ordinal
        return context


class ContinuityContractValidationError(ValueError):
    """A semantic contract failure that permits one bounded provider repair."""


def _contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value))


def _requires_cjk(value: str) -> bool:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", value))
    latin = len(re.findall(r"[A-Za-z]", value))
    return cjk >= 4 and cjk >= latin


def _temporal_anchor_is_explicit(value: str) -> bool:
    return bool(re.search(
        r"(?:\d{1,4}\s*(?:年|月|日|号|点|时|分|秒|章)|[一二三四五六七八九十百零两]+\s*(?:年|月|日|号|点|时|分|秒|章)|"
        r"同一(?:天|夜|晚|时刻|时间)|与此同时|同时|当时|此刻|刚落|之后|以前|以前|直到|"
        r"\b(?:same\s+(?:day|night|time|moment)|simultaneously|at\s+that\s+(?:time|moment)|before|after|until)\b)",
        value,
        re.IGNORECASE,
    ))


def _explicit_temporal_overlap(claim_anchor: str, evidence_anchor: str) -> bool:
    if not _temporal_anchor_is_explicit(claim_anchor) or not _temporal_anchor_is_explicit(evidence_anchor):
        return False
    component_pattern=r"(\d{1,4}|[一二三四五六七八九十百零两]+)\s*(年|月|日|号|点|时|分|秒|章)"
    unit_group={"号":"日","时":"点"}
    digit_map={"零":"0","一":"1","二":"2","两":"2","三":"3","四":"4","五":"5","六":"6","七":"7","八":"8","九":"9"}
    def normalized_number(raw:str)->str:
        if raw.isdigit():return str(int(raw))
        if "十" in raw and all(char in digit_map or char=="十" for char in raw):
            left,right=raw.split("十",1)
            return str((int(digit_map[left]) if left else 1)*10+(int(digit_map[right]) if right else 0))
        if all(char in digit_map for char in raw):return str(int("".join(digit_map[char] for char in raw)))
        return raw
    def components(value:str)->dict[str,set[str]]:
        parsed:dict[str,set[str]]={}
        for raw,unit in re.findall(component_pattern,value,re.IGNORECASE):
            parsed.setdefault(unit_group.get(unit,unit),set()).add(normalized_number(raw.casefold()))
        for raw in re.findall(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",value,re.IGNORECASE):
            parsed.setdefault("clock",set()).add(re.sub(r"\s+","",raw).casefold())
        return parsed
    claim_components=components(claim_anchor);evidence_components=components(evidence_anchor)
    shared_units=set(claim_components)&set(evidence_components)
    if claim_components or evidence_components:
        if any(claim_components[unit].isdisjoint(evidence_components[unit]) for unit in shared_units):return False
        return any(claim_components[unit]&evidence_components[unit] for unit in shared_units)
    relational_pattern=r"(?:同一(?:天|夜|晚|时刻|时间)|与此同时|同时|当时|此刻|\b(?:same\s+(?:day|night|time|moment)|simultaneously|at\s+that\s+(?:time|moment))\b)"
    return bool(re.search(relational_pattern,claim_anchor,re.IGNORECASE) and re.search(relational_pattern,evidence_anchor,re.IGNORECASE))


def _continuity_schema() -> dict[str, Any]:
    return {"issues":[{"claim_span_id":"current claim id","status":"conflict|insufficient_evidence","nature":"confirmed_conflict|possible_conflict|state_change|insufficient_evidence","category":"allowed category","severity":"low|medium|high","explanation":"short backwards-compatible summary","reasoning":"why the cited evidence supports this nature, or exactly what evidence is missing","temporal_basis":{"claim_anchor":"exact claim substring or null","evidence_anchor":"exact cited evidence substring or null","relation":"explicit_overlap|timeless_rule|explicit_later_transition|unknown"},"evidence":[{"chapter_id":"allowed chapter id","span_id":"allowed span id","relation":"supports|contradicts|context","sufficiency":"sufficient|insufficient","related_memory_ids":["known memory id"]}],"evidence_chain":[{"span_id":"one cited evidence span id","role":"prior_state|current_context|missing_link"}],"suggested_revision":{"before":"exact text occurring once in the bound draft","after":"specific replacement text"},"available_actions":["edit|apply_suggestion|keep_intentional|false_positive"],"proposed_memory_change":{"operation":"add|replace","memory_type":"allowed memory type","subject":"string","predicate":"string","value":"string","affected_memory_id":"required for replace only"}}]}


def _memory_schema() -> dict[str, Any]:
    return {"candidates":[{"memory_type":"static_canon|dynamic_state|event_timeline|character_knowledge|open_thread","subject":"string","predicate":"identity|relationship|affiliation|location|status|rule|possession|event_occurred|knowledge","value":"string","chapter_id":"source chapter id","source_span_id":"supplied source span id"}]}


def _memory_delta_schema() -> dict[str, Any]:
    return {"candidates":[{"change_kind":"new_fact|changed_fact|invalidated_fact","affected_memory_id":"null for new_fact; supplied confirmed Memory id for changed_fact or invalidated_fact","memory_type":"allowed memory type","subject":"string","predicate":"controlled predicate","value":"new/changed fact value; exact current value for invalidated_fact","invalidation_reason":"null for new_fact/changed_fact; non-empty reason for invalidated_fact","chapter_id":"source chapter id","source_span_id":"supplied current-revision SourceSpan id"}]}


def _aggregate(results: list[Any]) -> dict[str, Any]:
    def total(field: str):
        values=[getattr(result,field) for result in results if getattr(result,field) is not None]
        return sum(values) if values else None
    return {"input_tokens":total("input_tokens"),"output_tokens":total("output_tokens"),"latency_ms":total("latency_ms"),"cost_cny":total("cost_cny")}


def _invalid_json_aggregate(results: list[Any], error: ProviderInvalidJson) -> dict[str, Any]:
    return {**_aggregate(results+[error]), "finish_reason": error.finish_reason, "cost_available": error.cost_available}


def _claim_terms(text: str) -> set[str]:
    characters="".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]",text))
    return {characters[index:index+2] for index in range(max(0,len(characters)-1))}


def _relevance_score(terms:set[str],text:str)->int:
    return len(terms & _claim_terms(text))


def _memory_sort_key(item:dict[str,Any])->tuple[str,...]:
    return tuple(str(item.get(key,"")) for key in ("subject","predicate","value","source_span_id","id"))


def _bounded_excerpt(body:str,hints:list[str],limit:int=CONTINUITY_EVIDENCE_EXCERPT_CODEPOINTS)->str:
    if len(body)<=limit:return body
    phrases=[]
    for hint in hints:
        compact="".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]",hint))
        if len(compact)>=2:phrases.append(compact)
        phrases.extend(sorted(_claim_terms(hint)))
    anchor=next((body.find(phrase) for phrase in sorted(set(phrases),key=lambda value:(-len(value),value)) if body.find(phrase)>=0),0)
    start=max(0,anchor-limit//3); end=min(len(body),start+limit); start=max(0,end-limit)
    return body[start:end]


class ContinuityEngine:
    def __init__(self,provider:ProviderPort): self.provider=provider
    def provenance(self)->dict[str,str]:
        return {"provider_label":self.provider.label,"model_label":getattr(self.provider,"model_label",self.provider.label),"prompt_version":PROMPT_VERSION,"schema_version":"continuity-issue-v5-temporal-basis","retrieval_method_version":RETRIEVAL_METHOD_VERSION}

    def _selected_evidence(self,claim:dict[str,Any],memory:list[dict[str,Any]])->list[dict[str,Any]]:
        unique={span["id"]:span for span in claim["allowed_evidence"]}
        by_source:dict[str,list[dict[str,Any]]]={}
        for item in memory:by_source.setdefault(str(item.get("source_span_id","")),[]).append(item)
        terms=_claim_terms(claim["text"]); ranked=[]
        for span in unique.values():
            related=by_source.get(span["id"],[])
            memory_text=" ".join(str(item.get(key,"")) for item in related for key in ("subject","predicate","value"))
            score=10*_relevance_score(terms,memory_text)+min(20,_relevance_score(terms,str(span.get("body",""))))
            ranked.append((score,str(span.get("chapter_id","")),span["id"],span,related))
        selected=[]
        for _,_,_,span,related in sorted(ranked,key=lambda row:(-row[0],row[1],row[2]))[:CONTINUITY_EVIDENCE_LIMIT]:
            hints=[claim["text"]]+[str(item.get(key,"")) for item in sorted(related,key=_memory_sort_key) for key in ("subject","value")]
            selected.append({**span,"prompt_excerpt":_bounded_excerpt(str(span.get("body","")),hints)})
        return selected

    def _related_memory(self, claim: dict[str, Any], memory: list[dict[str, Any]]) -> list[dict[str, Any]]:
        terms=_claim_terms(claim["text"]); evidence_ids={span["id"] for span in claim["allowed_evidence"]}; ranked=[]
        for item in memory:
            text=" ".join(str(item.get(key,"")) for key in ("subject","predicate","value"))
            score=10*int(item.get("source_span_id") in evidence_ids)+_relevance_score(terms,text)
            if score:ranked.append((score,item))
        return [item for _,item in sorted(ranked,key=lambda row:(-row[0],_memory_sort_key(row[1])))[:RELATED_MEMORY_LIMIT]]

    def _request(self, claims: list[dict[str, Any]], memory: list[dict[str, Any]], draft: dict[str, Any]) -> dict[str, Any]:
        selected_claims=[{**claim,"allowed_evidence":self._selected_evidence(claim,memory)} for claim in claims]
        used={item["id"]:item for claim in selected_claims for item in self._related_memory(claim,memory)}
        return {"draft":{"id":draft["id"],"revision":draft["revision"],"body":"\n".join(claim["text"] for claim in selected_claims)},"claims":selected_claims,"memory":[used[key] for key in sorted(used)],"output_schema":_continuity_schema()}

    def _batches(self,data:dict[str,Any])->list[dict[str,Any]]:
        batches=[]; current=[]
        for claim in data["claims"]:
            candidate=current+[claim]; request=self._request(candidate,data["memory"],data["draft"])
            if request_prompt_and_budget(request)[1] <= MAX_INPUT_BUDGET_UNITS:
                current=candidate; continue
            if not current: raise InputBudgetExceeded()
            batches.append(self._request(current,data["memory"],data["draft"])); current=[claim]
            if request_prompt_and_budget(self._request(current,data["memory"],data["draft"]))[1] > MAX_INPUT_BUDGET_UNITS: raise InputBudgetExceeded()
        if current:batches.append(self._request(current,data["memory"],data["draft"]))
        return batches

    def _repair_diagnostics(self,payload:Any,data:dict[str,Any])->list[dict[str,Any]]:
        """Collect all independently detectable semantic contract failures for one repair call."""
        if not isinstance(payload,dict) or not isinstance(payload.get("issues"),list):return []
        claims={item["id"]:item for item in data["claims"]};mem={item["id"]:item for item in data["memory"]};diagnostics=[]
        for raw in payload["issues"]:
            if not isinstance(raw,dict) or raw.get("claim_span_id") not in claims:continue
            review_keys={"nature","reasoning","temporal_basis","evidence_chain","suggested_revision","available_actions"}
            if not review_keys<=set(raw):continue
            claim=claims[raw["claim_span_id"]];allowed={item["id"]:item for item in claim["allowed_evidence"]};codes=[]
            raw_evidence=raw.get("evidence") if isinstance(raw.get("evidence"),list) else []
            if _requires_cjk(data["draft"]["body"]):
                author_texts=[raw.get("explanation"),raw.get("reasoning")]
                if any(not isinstance(text,str) or not _contains_cjk(text) for text in author_texts):codes.append("author_language_mismatch")
            temporal=raw.get("temporal_basis")
            if raw.get("nature")=="confirmed_conflict" and isinstance(temporal,dict):
                claim_anchor=temporal.get("claim_anchor");evidence_anchor=temporal.get("evidence_anchor");relation=temporal.get("relation")
                if relation=="explicit_overlap":
                    if not isinstance(claim_anchor,str) or not isinstance(evidence_anchor,str) or not _explicit_temporal_overlap(claim_anchor,evidence_anchor):codes.append("temporal_overlap_unproven")
                elif relation=="timeless_rule":
                    related_ids={memory_id for evidence in raw_evidence if isinstance(evidence,dict) and isinstance(evidence.get("related_memory_ids"),list) for memory_id in evidence["related_memory_ids"] if memory_id in mem}
                    if not any(mem[memory_id].get("memory_type")=="static_canon" and mem[memory_id].get("predicate")=="rule" for memory_id in related_ids):codes.append("timeless_rule_unproven")
                else:codes.append("temporal_overlap_unproven")
            if codes:
                evidence_excerpts=[]
                for evidence in raw_evidence:
                    if isinstance(evidence,dict) and evidence.get("span_id") in allowed:
                        span=allowed[evidence["span_id"]]
                        evidence_excerpts.append({"span_id":span["id"],"excerpt":span.get("prompt_excerpt",span["body"])})
                diagnostics.append({"claim_span_id":claim["id"],"claim_text":claim["text"],"problem_codes":list(dict.fromkeys(codes)),"cited_evidence":evidence_excerpts})
        return diagnostics

    def execute(self,data:dict[str,Any])->dict[str,Any]:
        if not self.provider.available:return {"status":"failed","error_code":"provider_unavailable","retryable":True}
        try:batches=self._batches(data)
        except InputBudgetExceeded:return {"status":"failed","error_code":"input_budget_exceeded","retryable":True}
        results=[]; issues=[];contract_normalizations=[]
        retrieval_traces=[{"claim_id":claim["id"],"returned_span_ids":[span["id"] for span in claim["allowed_evidence"]]} for batch in batches for claim in batch["claims"]]
        try:
            for batch in batches:
                for contract_attempt in range(2):
                    request=batch if contract_attempt==0 else {**batch,"contract_repair":{"attempt":contract_attempt+1,"reason_code":repair_code,"diagnostics":repair_diagnostics,"rejected_issues":rejected_issues}}
                    result=self.provider.evaluate(request)
                    if (result.input_tokens or 0)+(result.output_tokens or 0)>MAX_RUN_TOKENS:return {"status":"budget_paused","error_code":"budget_paused","retryable":True,**_aggregate(results+[result])}
                    results.append(result)
                    repair_diagnostics=self._repair_diagnostics(result.payload,batch)
                    if contract_attempt==0 and repair_diagnostics:
                        repair_code=repair_diagnostics[0]["problem_codes"][0]
                        rejected_issues=result.payload.get("issues",[]) if isinstance(result.payload,dict) else []
                        continue
                    try:
                        validated=self.validate(result.payload,batch,allow_conservative_temporal_normalization=contract_attempt==1,normalization_sink=contract_normalizations)
                    except ContinuityContractValidationError as error:
                        if contract_attempt==0:
                            repair_code=str(error)
                            repair_diagnostics=[{"claim_span_id":None,"claim_text":None,"problem_codes":[repair_code],"cited_evidence":[]}]
                            rejected_issues=result.payload.get("issues",[]) if isinstance(result.payload,dict) else []
                            continue
                        raise
                    issues.extend(validated)
                    break
        except InputBudgetExceeded:return {"status":"failed","error_code":"input_budget_exceeded","retryable":True,**_aggregate(results)}
        except ProviderUnavailable:return {"status":"failed","error_code":"provider_unavailable","retryable":True,**_aggregate(results)}
        except ProviderTimeout:return {"status":"timed_out","error_code":"provider_timeout","retryable":True,**_aggregate(results)}
        except ProviderInvalidJson as error:return {"status":"failed","error_code":"invalid_json","retryable":True,**_invalid_json_aggregate(results,error)}
        except ProviderFailure:return {"status":"failed","error_code":"provider_error","retryable":True,**_aggregate(results)}
        except ValueError as error:return {"status":"failed","error_code":str(error),"retryable":True,**_aggregate(results)}
        order={claim["id"]:index for index,claim in enumerate(data["claims"])}
        if len({issue["claim_span_id"] for issue in issues}) != len(issues): return {"status":"failed","error_code":"schema_invalid","retryable":True,**_aggregate(results)}
        return {"status":"completed","issues":sorted(issues,key=lambda item:order[item["claim_span_id"]]),"retrieval_traces":retrieval_traces,"retrieval_method_version":RETRIEVAL_METHOD_VERSION,"contract_normalization_count":len(contract_normalizations),"contract_normalizations":contract_normalizations,**_aggregate(results)}

    def validate(self,payload:Any,data:dict[str,Any],allow_conservative_temporal_normalization:bool=False,normalization_sink:list[dict[str,Any]]|None=None):
        if not isinstance(payload,dict) or set(payload)!={"issues"} or not isinstance(payload.get("issues"),list):raise ValueError("schema_invalid")
        claims={x["id"]:x for x in data["claims"]}; mem={x["id"]:x for x in data["memory"]}; output=[]
        for raw in payload["issues"]:
            if raw.get("status")=="no_conflict":raise ValueError("no_conflict_issue_forbidden")
            explanation=raw.get("explanation") if isinstance(raw,dict) else None
            if not isinstance(raw,dict) or raw.get("claim_span_id") not in claims or raw.get("status") not in ALLOWED_STATUS or raw.get("category") not in ALLOWED_CATEGORY or raw.get("severity") not in ALLOWED_SEVERITY or not isinstance(explanation,str) or not explanation.strip():raise ValueError("schema_invalid")
            review_keys={"nature","reasoning","temporal_basis","evidence_chain","suggested_revision","available_actions"}
            present=review_keys & set(raw)
            if not present and not getattr(self.provider,"allows_legacy_continuity_contract",False):raise ContinuityContractValidationError("trustworthy_review_required")
            if present==review_keys-{"temporal_basis"}:raise ContinuityContractValidationError("temporal_basis_missing")
            if present and present!=review_keys:raise ValueError("schema_invalid")
            trustworthy=present==review_keys
            evs=raw.get("evidence",[]); allowed={x["id"]:x for x in claims[raw["claim_span_id"]]["allowed_evidence"]}
            if raw["status"]=="conflict" and not evs:raise ValueError("conflict_without_evidence")
            if raw["status"]=="insufficient_evidence" and evs and not trustworthy:raise ValueError("insufficient_evidence_upgraded")
            if raw["status"]=="insufficient_evidence" and raw.get("proposed_memory_change") is not None:raise ValueError("insufficient_evidence_memory_change")
            cleaned=[]
            for ev in evs:
                if not isinstance(ev,dict) or ev.get("span_id") not in allowed:raise ValueError("evidence_unresolvable")
                s=allowed[ev["span_id"]]
                if ev.get("chapter_id")!=s["chapter_id"] or ev.get("relation") not in {"supports","contradicts","context"} or ev.get("sufficiency") not in {"sufficient","insufficient"} or not set(ev.get("related_memory_ids",[]))<=set(mem):raise ValueError("evidence_unresolvable")
                if raw["status"]=="conflict" and not trustworthy and (ev.get("relation")!="contradicts" or ev.get("sufficiency")!="sufficient"):raise ValueError("conflict_evidence_not_direct")
                if raw["status"]=="insufficient_evidence" and ev.get("sufficiency")!="insufficient":raise ValueError("insufficient_evidence_upgraded")
                cleaned.append({"chapter_id":s["chapter_id"],"span_id":s["id"],"excerpt":s.get("prompt_excerpt",s["body"]),"relation":ev["relation"],"sufficiency":ev["sufficiency"],"related_memory_ids":ev.get("related_memory_ids",[])})
            change=raw.get("proposed_memory_change")
            if change is not None:
                required={"memory_type","subject","predicate","value","operation"}
                if (not isinstance(change,dict) or not required<=set(change) or change["memory_type"] not in ALLOWED_MEMORY_TYPE or change["operation"] not in {"add","replace"} or any(not isinstance(change[key],str) or not change[key].strip() for key in ("subject","predicate","value")) or (change["operation"]=="add" and change.get("affected_memory_id") is not None) or (change["operation"]=="replace" and change.get("affected_memory_id") not in mem) or raw["status"]!="conflict"):raise ValueError("schema_invalid")
            review={"review_contract_version":"legacy_v3","nature":None,"reasoning":None,"evidence_chain":None,"suggested_revision":None,"available_actions":None}
            if trustworthy:
                nature=raw.get("nature");reasoning=raw.get("reasoning");temporal=raw.get("temporal_basis");chain=raw.get("evidence_chain");suggestion=raw.get("suggested_revision");actions=raw.get("available_actions")
                if nature not in REVIEW_NATURES or not isinstance(reasoning,str) or not reasoning.strip() or len(reasoning.strip())>800:raise ValueError("schema_invalid")
                if not isinstance(temporal,dict) or set(temporal)!={"claim_anchor","evidence_anchor","relation"} or temporal.get("relation") not in {"explicit_overlap","timeless_rule","explicit_later_transition","unknown"}:raise ValueError("schema_invalid")
                claim_text=claims[raw["claim_span_id"]]["text"]
                claim_anchor=temporal.get("claim_anchor");evidence_anchor=temporal.get("evidence_anchor")
                if claim_anchor is not None and (not isinstance(claim_anchor,str) or not claim_anchor.strip() or claim_anchor not in claim_text):raise ContinuityContractValidationError("temporal_anchor_unresolvable")
                if evidence_anchor is not None and (not isinstance(evidence_anchor,str) or not evidence_anchor.strip() or not any(evidence_anchor in item["excerpt"] for item in cleaned)):raise ContinuityContractValidationError("temporal_anchor_unresolvable")
                if _requires_cjk(data["draft"]["body"]):
                    author_texts=[explanation,reasoning]
                    if any(not _contains_cjk(text) for text in author_texts):raise ContinuityContractValidationError("author_language_mismatch")
                if raw["status"]=="insufficient_evidence" and nature!="insufficient_evidence":raise ValueError("schema_invalid")
                if raw["status"]=="conflict" and nature=="insufficient_evidence":raise ValueError("schema_invalid")
                if nature=="confirmed_conflict" and any(ev["relation"]!="contradicts" or ev["sufficiency"]!="sufficient" for ev in cleaned):raise ValueError("conflict_evidence_not_direct")
                temporal_failure=None
                if nature=="confirmed_conflict":
                    if temporal["relation"]=="explicit_overlap":
                        if not isinstance(claim_anchor,str) or not isinstance(evidence_anchor,str) or not _explicit_temporal_overlap(claim_anchor,evidence_anchor):temporal_failure="temporal_overlap_unproven"
                    elif temporal["relation"]=="timeless_rule":
                        related_ids={memory_id for item in cleaned for memory_id in item["related_memory_ids"]}
                        if not any(mem[memory_id].get("memory_type")=="static_canon" and mem[memory_id].get("predicate")=="rule" for memory_id in related_ids):temporal_failure="timeless_rule_unproven"
                    else:temporal_failure="temporal_overlap_unproven"
                    if temporal_failure and not allow_conservative_temporal_normalization:raise ContinuityContractValidationError(temporal_failure)
                if nature in {"possible_conflict","state_change"} and any(ev["sufficiency"]!="sufficient" for ev in cleaned):raise ValueError("evidence_unresolvable")
                if nature=="insufficient_evidence" and (not cleaned or any(ev["sufficiency"]!="insufficient" for ev in cleaned)):raise ValueError("evidence_unresolvable")
                if not isinstance(chain,list) or len(chain)!=len(cleaned) or any(not isinstance(item,dict) or set(item)!={"span_id","role"} or item.get("role") not in EVIDENCE_CHAIN_ROLES for item in chain):raise ValueError("evidence_unresolvable")
                chain_spans=[item["span_id"] for item in chain]
                if len(chain_spans)!=len(set(chain_spans)) or set(chain_spans)!={item["span_id"] for item in cleaned}:raise ValueError("evidence_unresolvable")
                if nature=="insufficient_evidence" and any(item["role"]!="missing_link" for item in chain):raise ValueError("evidence_unresolvable")
                if not isinstance(actions,list) or len(actions)!=len(set(actions)) or not set(actions)<=REVIEW_ACTIONS:raise ValueError("schema_invalid")
                if nature=="insufficient_evidence" and actions:raise ValueError("schema_invalid")
                if suggestion is not None:
                    if not isinstance(suggestion,dict) or set(suggestion)!={"before","after"} or any(not isinstance(suggestion.get(field),str) or not suggestion[field].strip() for field in ("before","after")) or suggestion["before"]==suggestion["after"]:raise ValueError("schema_invalid")
                    if data["draft"]["body"].count(suggestion["before"])!=1 or "apply_suggestion" not in actions:raise ValueError("suggested_revision_unresolvable")
                elif "apply_suggestion" in actions:raise ValueError("suggested_revision_unresolvable")
                if temporal_failure and allow_conservative_temporal_normalization:
                    chinese=_requires_cjk(data["draft"]["body"])
                    safe_explanation=("现有材料不足以证明当前主张与引用事实在同一故事时间和范围内相互矛盾，暂不能判定为确定冲突。" if chinese else "The supplied material does not establish that the current claim and cited fact conflict in the same story time and scope, so a confirmed conflict cannot be established.")
                    safe_reasoning=("需要补充明确的时间锚点、适用范围或连接事件，才能判断两项陈述是否不能同时成立。" if chinese else "An explicit time anchor, applicable scope, or connecting event is required before deciding that the two statements cannot coexist.")
                    insufficient=[{**item,"relation":"context","sufficiency":"insufficient"} for item in cleaned]
                    if normalization_sink is not None:normalization_sink.append({"claim_span_id":raw["claim_span_id"],"reason_code":temporal_failure,"outcome":"insufficient_evidence","provider_attempt":2})
                    output.append({"claim_span_id":raw["claim_span_id"],"status":"insufficient_evidence","category":raw["category"],"severity":"medium","evidence_status":"insufficient","explanation":safe_explanation,"evidence":insufficient,"proposed_memory_change":None,"review_contract_version":"trustworthy_review_v1","nature":"insufficient_evidence","reasoning":safe_reasoning,"evidence_chain":[{"span_id":item["span_id"],"role":"missing_link"} for item in insufficient],"suggested_revision":None,"available_actions":[]})
                    continue
                if nature=="confirmed_conflict" and temporal["relation"]=="timeless_rule" and suggestion is not None:
                    suggestion=None;actions=[action for action in actions if action!="apply_suggestion"]
                review={"review_contract_version":"trustworthy_review_v1","nature":nature,"reasoning":reasoning.strip(),"evidence_chain":chain,"suggested_revision":suggestion,"available_actions":actions}
            output.append({"claim_span_id":raw["claim_span_id"],"status":raw["status"],"category":raw["category"],"severity":raw["severity"],"evidence_status":"sufficient" if cleaned and all(item["sufficiency"]=="sufficient" for item in cleaned) else "insufficient","explanation":explanation.strip()[:500],"evidence":cleaned,"proposed_memory_change":change,**review})
        return output


class WritingAnalysisEngine:
    """Strict, bounded analysis over one immutable database-prepared input."""
    def __init__(self,provider:ProviderPort):self.provider=provider

    def provenance(self,analysis_type:str)->dict[str,str]:
        prompt_version=CONTEXT_BRIEF_PROMPT_VERSION if analysis_type=="context_brief" else PLAN_ALIGNMENT_PROMPT_VERSION if analysis_type=="plan_alignment" else CHANGE_IMPACT_PROMPT_VERSION if analysis_type=="change_impact" else STORY_QA_PROMPT_VERSION if analysis_type=="story_qa" else FORESHADOW_SCAN_PROMPT_VERSION if analysis_type=="foreshadow_scan" else AUTHOR_MATERIAL_COMPARISON_PROMPT_VERSION if analysis_type=="author_material_comparison" else REVISION_PLAN_PROMPT_VERSION
        schema_version="writing-analysis-v2-foreshadow-evidence-kind" if analysis_type=="foreshadow_scan" else "writing-analysis-v1"
        return {"provider_label":self.provider.label,"model_label":getattr(self.provider,"model_label",self.provider.label),"prompt_version":prompt_version,"schema_version":schema_version,"retrieval_method_version":ANALYSIS_RETRIEVAL_METHOD_VERSION}

    @staticmethod
    def _schema(task:str)->dict[str,Any]:
        if task=="author_material_comparison":
            return {"assessment":"aligned|possible_tension|plan_deviation|insufficient_evidence","explanation":"1-600 chars","evidence":[{"source_type":"author_material|source_span","source_id":"supplied id"}]}
        if task=="context_brief":
            return {"summary":"1-400 chars","summary_sources":[{"source_type":"author_context|memory_record|source_span|draft_claim","source_id":"supplied id"}],"items":[{"section":"related_plan|confirmed_fact|character_state|world_rule|open_thread|recent_source","text":"1-600 chars","sources":[{"source_type":"author_context|memory_record|source_span|draft_claim","source_id":"supplied id"}]}]}
        if task=="change_impact":
            return {"summary":"1-400 chars","items":[{"area":"chapter|character|world|memory|plan","target_id":"supplied target id","impact":"1-600 chars; analysis only, never replacement prose","evidence":[{"source_type":"author_context|memory_record|source_span|draft_claim|character_record|character_alias|world_record","source_id":"supplied id"}]}]}
        if task=="story_qa":
            return {"answer_status":"answered|partial|insufficient|conflicting","answer":"1-800 chars","findings":[{"layer":"confirmed|written|planned","stance":"supports|contradicts|context","text":"1-600 chars","evidence":[{"source_type":"memory_record|source_span|draft_claim|author_context","source_id":"supplied id"}]}]}
        if task=="foreshadow_scan":
            return {"summary":"1-400 chars","candidates":[{"title":"1-120 chars","description":"1-1200 chars","suggested_status":"planted|developing|resolved","evidence":[{"source_type":"source_span|draft_claim","source_id":"supplied id","relation":"planted|developing|resolved","evidence_kind":"current_clue|specific_prior_unresolved_clue|background_only|explicit_payoff"}]}]}
        if task=="revision_plan":
            return {"summary":"1-400 chars","candidates":[{"issue_id":"one supplied selected issue id","title":"1-120 chars","instruction":"1-1200 chars; an editing action, never replacement prose","priority":"high|medium|low","evidence":[{"source_type":"issue_evidence","source_id":"evidence id supplied for that issue"}]}]}
        return {"summary":"1-400 chars","items":[{"story_plan_id":"supplied story plan id","status":"planned_covered|planned_missing|planned_early|planned_changed|insufficient_evidence","explanation":"1-600 chars","evidence":[{"source_type":"draft_claim|source_span","source_id":"supplied id"}]}]}

    def _request(self,data:dict[str,Any])->dict[str,Any]:
        return {**data,"output_schema":self._schema(data["task"])}

    @staticmethod
    def _text(value:Any,limit:int)->str:
        if not isinstance(value,str) or not value.strip() or len(value.strip())>limit:raise ValueError("schema_invalid")
        return value.strip()

    @staticmethod
    def _source_maps(data:dict[str,Any])->dict[str,dict[str,dict[str,Any]]]:
        planned=data["layers"]["planned"]
        author={}
        for group_name,group in planned.items():
            route="outline" if group_name=="story_plans" else "characters" if group_name=="character_plans" else "world"
            for item in group:author[item["id"]]={**item,"_source_route":route}
        memory={item["id"]:item for item in data["layers"]["confirmed"]["memory_records"]}
        written=data["layers"]["written"]
        identity=data["layers"].get("identity",{});reference=data["layers"].get("reference",{})
        issue_evidence={item["id"]:item for issue in data.get("selected_issues",[]) for item in issue.get("evidence",[])}
        return {"author_context":author,"author_material":author,"memory_record":memory,"source_span":{item["id"]:item for item in written["source_spans"]},"draft_claim":{item["id"]:item for item in written["draft_claims"]},"character_record":{item["id"]:item for item in identity.get("characters",[])},"character_alias":{item["id"]:item for item in identity.get("aliases",[])},"world_record":{item["id"]:item for item in reference.get("world_entries",[])},"issue_evidence":issue_evidence}

    @classmethod
    def _clean_source(cls,raw:Any,maps:dict[str,dict[str,dict[str,Any]]],allowed:set[str],project_id:str)->dict[str,Any]:
        if not isinstance(raw,dict) or set(raw)!={"source_type","source_id"} or raw.get("source_type") not in allowed:raise ValueError("evidence_unresolvable")
        source_type=raw["source_type"];source_id=raw.get("source_id")
        if not isinstance(source_id,str) or source_id not in maps[source_type]:raise ValueError("evidence_unresolvable")
        item=maps[source_type][source_id]
        if source_type in {"author_context","author_material"}:label=item.get("title") or item.get("name") or "Author Context";excerpt=item.get("content") or item.get("summary") or item.get("goal") or item.get("planned_state") or item.get("description") or ""
        elif source_type=="memory_record":label=f"{item['subject']} · {item['predicate']}";excerpt=item["value"]
        elif source_type=="draft_claim":label=f"当前草稿 · 句 {item['ordinal']}";excerpt=item["text"]
        elif source_type=="character_record":label=item["name"];excerpt=" · ".join(filter(None,(item.get("identity"),item.get("current_state"),item.get("knowledge_boundary"))))
        elif source_type=="character_alias":label=f"{item['primary_name']} · 别名";excerpt=item["alias"]
        elif source_type=="world_record":label=item["name"];excerpt=item["summary"]
        elif source_type=="issue_evidence":label=f"第 {item['chapter_number']} 章 · {item['chapter_title']}";excerpt=item["excerpt"]
        else:label=f"第 {item['chapter_number']} 章 · {item['label']}";excerpt=item["body"]
        if source_type in {"author_context","author_material"}:source_path=f"/projects/{project_id}/{item['_source_route']}#plan-{source_id}"
        elif source_type=="memory_record":source_path=f"/projects/{project_id}/memory#memory-{source_id}"
        elif source_type=="draft_claim":source_path=f"/projects/{project_id}/workspace#draft-source"
        elif source_type=="character_record":source_path=f"/projects/{project_id}/characters?character={source_id}#character-{source_id}"
        elif source_type=="character_alias":source_path=f"/projects/{project_id}/characters?character={item['character_id']}#alias-{source_id}"
        elif source_type=="world_record":source_path=f"/projects/{project_id}/world?world={source_id}#world-{source_id}"
        elif source_type=="issue_evidence":source_path=item["source_path"]
        else:source_path=f"/projects/{project_id}/sources#span-{source_id}"
        return {"source_type":source_type,"source_id":source_id,"label":str(label)[:160],"excerpt":str(excerpt)[:900],"source_path":source_path}

    def validate(self,payload:Any,data:dict[str,Any])->dict[str,Any]:
        maps=self._source_maps(data);task=data["task"];project_id=data["bindings"]["project_id"]
        if task=="author_material_comparison":
            if not isinstance(payload,dict) or set(payload)!={"assessment","explanation","evidence"} or payload.get("assessment") not in {"aligned","possible_tension","plan_deviation","insufficient_evidence"} or not isinstance(payload.get("evidence"),list):raise ValueError("schema_invalid")
            material=data["comparison"]["material"]
            if payload["assessment"]=="plan_deviation" and material["nature"]!="plan":raise ValueError("schema_invalid")
            if payload["assessment"]=="insufficient_evidence":
                if len(payload["evidence"])>2:raise ValueError("evidence_unresolvable")
            elif len(payload["evidence"])!=2:raise ValueError("evidence_unresolvable")
            evidence=[self._clean_source(item,maps,{"author_material","source_span"},project_id) for item in payload["evidence"]]
            if payload["assessment"]!="insufficient_evidence" and {(item["source_type"],item["source_id"]) for item in evidence}!={("author_material",material["id"]),("source_span",data["comparison"]["passage"]["id"])}:raise ValueError("evidence_unresolvable")
            return {"assessment":payload["assessment"],"explanation":self._text(payload["explanation"],600),"evidence":evidence,"comparison_id":data["bindings"]["comparison_id"],"decision_revision":data["bindings"]["decision_revision"]}
        if task=="context_brief":
            if not isinstance(payload,dict) or set(payload)!={"summary","summary_sources","items"} or not isinstance(payload["summary_sources"],list) or not isinstance(payload["items"],list) or not 1<=len(payload["summary_sources"])<=3 or not 1<=len(payload["items"])<=12:raise ValueError("schema_invalid")
            summary_sources=[self._clean_source(item,maps,{"author_context","memory_record","source_span","draft_claim"},project_id) for item in payload["summary_sources"]]
            items=[]
            for raw in payload["items"]:
                if not isinstance(raw,dict) or set(raw)!={"section","text","sources"} or raw.get("section") not in CONTEXT_BRIEF_SECTIONS or not isinstance(raw.get("sources"),list) or not 1<=len(raw["sources"])<=4:raise ValueError("schema_invalid")
                sources=[self._clean_source(item,maps,{"author_context","memory_record","source_span","draft_claim"},project_id) for item in raw["sources"]]
                items.append({"section":raw["section"],"text":self._text(raw["text"],600),"sources":sources})
            deterministic_summary=[];deterministic_sources=[];source_keys=set()
            section_order={name:index for index,name in enumerate(("recent_source","related_plan","confirmed_fact","character_state","world_rule","open_thread"))}
            for item in sorted(items,key=lambda value:section_order[value["section"]]):
                candidate_keys={(source["source_type"],source["source_id"]) for source in item["sources"]}
                if len(source_keys|candidate_keys)>3:continue
                candidate_text=" ".join([*deterministic_summary,item["text"]])
                if len(candidate_text)>400:continue
                deterministic_summary.append(item["text"]);source_keys.update(candidate_keys)
                for source in item["sources"]:
                    key=(source["source_type"],source["source_id"])
                    if key not in {(value["source_type"],value["source_id"]) for value in deterministic_sources}:deterministic_sources.append(source)
            if not deterministic_summary:
                fallback_sources=items[0]["sources"][:3]
                draft_excerpt=str(data["layers"]["written"]["draft"].get("excerpt", ""))
                fallback_summary="已根据所列来源整理当前写作上下文，具体事实与引用见分项。" if _requires_cjk(draft_excerpt) else "Writing context was organized from the listed sources; see item-level citations for factual details."
                deterministic_summary=[fallback_summary];deterministic_sources=fallback_sources
            return {"summary":" ".join(deterministic_summary),"summary_sources":deterministic_sources,"items":items}
        if task=="change_impact":
            if not isinstance(payload,dict) or set(payload)!={"summary","items"} or not isinstance(payload["items"],list) or len(payload["items"])>20:raise ValueError("schema_invalid")
            layers=data["layers"]
            targets={"chapter":{item["id"]:f"第 {item['chapter_number']} 章 · {item['title']}" for item in layers["reference"]["chapters"]},"character":{item["id"]:item["name"] for item in layers["identity"]["characters"]},"world":{item["id"]:item["name"] for item in layers["reference"]["world_entries"]},"memory":{item["id"]:f"{item['subject']} · {item['predicate']}" for item in layers["confirmed"]["memory_records"]},"plan":{item["id"]:(item.get("title") or item.get("name") or "创作计划") for group in layers["planned"].values() for item in group}}
            allowed={"author_context","memory_record","source_span","draft_claim","character_record","character_alias","world_record"};items=[];seen=set()
            for raw in payload["items"]:
                if not isinstance(raw,dict) or set(raw)!={"area","target_id","impact","evidence"} or raw.get("area") not in targets or raw.get("target_id") not in targets[raw["area"]] or (raw["area"],raw["target_id"]) in seen or not isinstance(raw.get("evidence"),list) or not 1<=len(raw["evidence"])<=5:raise ValueError("evidence_unresolvable")
                evidence=[self._clean_source(item,maps,allowed,project_id) for item in raw["evidence"]]
                seen.add((raw["area"],raw["target_id"]));items.append({"area":raw["area"],"target_id":raw["target_id"],"label":targets[raw["area"]][raw["target_id"]],"impact":self._text(raw["impact"],600),"evidence":evidence})
            if not items:return {"summary":CHANGE_IMPACT_INSUFFICIENT_SUMMARY,"evidence_status":"insufficient","items":[],"proposal":data["proposal"]}
            return {"summary":self._text(payload["summary"],400),"evidence_status":"supported","items":items,"proposal":data["proposal"]}
        if task=="story_qa":
            if not isinstance(payload,dict) or set(payload)!={"answer_status","answer","findings"} or payload.get("answer_status") not in STORY_QA_STATUSES or not isinstance(payload.get("findings"),list) or len(payload["findings"])>12:raise ValueError("schema_invalid")
            if payload["answer_status"]=="insufficient":
                if payload["findings"]:raise ValueError("evidence_unresolvable")
                return {"summary":STORY_QA_INSUFFICIENT_ANSWER,"items":[],"answer_status":"insufficient","answer":STORY_QA_INSUFFICIENT_ANSWER,"evidence_status":"insufficient","findings":[],"question":data["question"],"scope":data["scope"]}
            if not payload["findings"]:raise ValueError("evidence_unresolvable")
            layer_sources={"confirmed":{"memory_record"},"written":{"source_span","draft_claim"},"planned":{"author_context"}}
            findings=[];stances=set();source_keys=set()
            for raw in payload["findings"]:
                if not isinstance(raw,dict) or set(raw)!={"layer","stance","text","evidence"} or raw.get("layer") not in STORY_QA_LAYERS or raw["layer"] not in data["scope"] or raw.get("stance") not in {"supports","contradicts","context"} or not isinstance(raw.get("evidence"),list) or not 1<=len(raw["evidence"])<=4:raise ValueError("evidence_unresolvable")
                evidence=[self._clean_source(item,maps,layer_sources[raw["layer"]],project_id) for item in raw["evidence"]]
                stances.add(raw["stance"]);source_keys.update((item["source_type"],item["source_id"]) for item in evidence)
                findings.append({"layer":raw["layer"],"stance":raw["stance"],"text":self._text(raw["text"],600),"evidence":evidence})
            if payload["answer_status"]=="conflicting" and (not {"supports","contradicts"}<=stances or len(source_keys)<2):raise ValueError("evidence_unresolvable")
            answer=self._text(payload["answer"],800)
            return {"summary":answer,"items":[],"answer_status":payload["answer_status"],"answer":answer,"evidence_status":"supported","findings":findings,"question":data["question"],"scope":data["scope"]}
        if task=="foreshadow_scan":
            if not isinstance(payload,dict) or set(payload)!={"summary","candidates"} or not isinstance(payload.get("candidates"),list) or len(payload["candidates"])>20:raise ValueError("schema_invalid")
            if not payload["candidates"]:return {"summary":FORESHADOW_INSUFFICIENT_SUMMARY,"items":[],"evidence_status":"insufficient","candidates":[]}
            existing={re.sub(r"\s+","",str(item["title"])).casefold() for item in data["author_records"]["foreshadows"]};seen=set();candidates=[];normalized_background=False
            written=data["layers"]["written"];span_map={item["id"]:item for item in written["source_spans"]}
            for raw in payload["candidates"]:
                if not isinstance(raw,dict) or set(raw)!={"title","description","suggested_status","evidence"} or raw.get("suggested_status") not in {"planted","developing","resolved"} or not isinstance(raw.get("evidence"),list) or not 1<=len(raw["evidence"])<=5:raise ValueError("evidence_unresolvable")
                title=self._text(raw["title"],120);normalized=re.sub(r"\s+","",title).casefold()
                description=self._text(raw["description"],1200)
                if normalized in existing or normalized in seen:raise ValueError("foreshadow_candidate_duplicate")
                seen.add(normalized);evidence=[];planted=None;resolved=None
                for source in raw["evidence"]:
                    if not isinstance(source,dict) or set(source) not in ({"source_type","source_id","relation"},{"source_type","source_id","relation","evidence_kind"}) or source.get("relation") not in {"planted","developing","resolved"}:raise ValueError("evidence_unresolvable")
                    evidence_kind=source.get("evidence_kind")
                    if evidence_kind is not None and evidence_kind not in {"current_clue","specific_prior_unresolved_clue","background_only","explicit_payoff"}:raise ValueError("evidence_unresolvable")
                    cleaned=self._clean_source({"source_type":source.get("source_type"),"source_id":source.get("source_id")},maps,{"source_span","draft_claim"},project_id);cleaned["relation"]=source["relation"]
                    if evidence_kind is not None:cleaned["evidence_kind"]=evidence_kind
                    evidence.append(cleaned)
                    span=span_map.get(source.get("source_id"))
                    locatable=evidence_kind not in {"background_only","current_clue"}
                    if span and locatable and source["relation"] in {"planted","developing"} and planted is None:planted={"chapter_id":span["chapter_id"],"source_span_id":span["id"]}
                    if span and locatable and source["relation"]=="resolved" and resolved is None:resolved={"chapter_id":span["chapter_id"],"source_span_id":span["id"]}
                suggested_status=raw["suggested_status"]
                typed_count=sum("evidence_kind" in source for source in evidence)
                if typed_count not in {0,len(evidence)}:raise ValueError("evidence_unresolvable")
                if typed_count==0 and not getattr(self.provider,"allows_legacy_foreshadow_evidence_contract",False):raise ValueError("evidence_kind_required")
                typed_evidence=typed_count==len(evidence)
                has_specific_prior=any(source["source_type"]=="source_span" and source.get("evidence_kind")=="specific_prior_unresolved_clue" for source in evidence)
                if suggested_status=="developing" and typed_evidence and not has_specific_prior:
                    evidence=[{**source,"relation":"planted"} for source in evidence if source["source_type"]=="draft_claim" and source.get("evidence_kind")=="current_clue"]
                    if not evidence:raise ValueError("evidence_unresolvable")
                    description=("当前草稿中的候选线索：" if _requires_cjk(written["draft"].get("excerpt","")) else "Candidate clue in the current draft: ")+evidence[0]["excerpt"]
                    description=self._text(description[:1200],1200)
                    suggested_status="planted";planted=None;normalized_background=True
                if suggested_status not in {source["relation"] for source in evidence}:raise ValueError("evidence_unresolvable")
                candidates.append({"title":title,"description":description,"suggested_status":suggested_status,"planted_chapter_id":planted["chapter_id"] if planted else None,"planted_source_span_id":planted["source_span_id"] if planted else None,"resolved_chapter_id":resolved["chapter_id"] if resolved else None,"resolved_source_span_id":resolved["source_span_id"] if resolved else None,"evidence":evidence})
            summary=("发现可供作者复核的伏笔候选：" if _requires_cjk(written["draft"].get("excerpt","")) else "Foreshadow candidates for author review: ")+"、".join(item["title"] for item in candidates) if normalized_background else self._text(payload["summary"],400)
            return {"summary":self._text(summary[:400],400),"items":[],"evidence_status":"supported","candidates":candidates}
        if task=="revision_plan":
            selected={item["id"]:item for item in data["selected_issues"]}
            if not isinstance(payload,dict) or set(payload)!={"summary","candidates"} or not isinstance(payload.get("candidates"),list) or len(payload["candidates"])!=len(selected):raise ValueError("revision_plan_candidate_count_invalid")
            candidates=[];seen_issues=set();seen_titles=set()
            for raw in payload["candidates"]:
                if not isinstance(raw,dict) or set(raw)!={"issue_id","title","instruction","priority","evidence"} or raw.get("issue_id") not in selected or raw["issue_id"] in seen_issues or raw.get("priority") not in REVISION_TASK_PRIORITIES or not isinstance(raw.get("evidence"),list) or not 1<=len(raw["evidence"])<=5:raise ValueError("revision_plan_candidate_invalid")
                title=self._text(raw["title"],120);normalized=re.sub(r"\s+","",title).casefold()
                if normalized in seen_titles:raise ValueError("revision_plan_candidate_duplicate")
                issue=selected[raw["issue_id"]];allowed_ids={item["id"] for item in issue["evidence"]}
                evidence=[]
                for source in raw["evidence"]:
                    if not isinstance(source,dict) or set(source)!={"source_type","source_id"} or source.get("source_type")!="issue_evidence" or source.get("source_id") not in allowed_ids:raise ValueError("evidence_unresolvable")
                    evidence.append(self._clean_source(source,maps,{"issue_evidence"},project_id))
                seen_issues.add(raw["issue_id"]);seen_titles.add(normalized);candidates.append({"issue_id":raw["issue_id"],"title":title,"instruction":self._text(raw["instruction"],1200),"priority":raw["priority"],"evidence":evidence})
            if seen_issues!=set(selected):raise ValueError("revision_plan_candidate_count_invalid")
            return {"summary":self._text(payload["summary"],400),"items":[],"evidence_status":"supported","candidates":candidates,"source_run_id":data["source_run_id"],"selected_issue_ids":list(selected)}
        if not isinstance(payload,dict) or set(payload)!={"summary","items"} or not isinstance(payload["items"],list):raise ValueError("schema_invalid")
        plans={item["id"]:item for item in data["layers"]["planned"]["story_plans"]}
        if len(payload["items"])!=len(plans):raise ValueError("schema_invalid")
        seen=set();items=[]
        for raw in payload["items"]:
            if not isinstance(raw,dict) or set(raw)!={"story_plan_id","status","explanation","evidence"} or raw.get("story_plan_id") not in plans or raw["story_plan_id"] in seen or raw.get("status") not in PLAN_ALIGNMENT_STATUSES or not isinstance(raw.get("evidence"),list) or len(raw["evidence"])>5:raise ValueError("schema_invalid")
            evidence=[self._clean_source(item,maps,{"draft_claim","source_span"},project_id) for item in raw["evidence"]]
            if raw["status"] in {"planned_covered","planned_early","planned_changed"} and not evidence:raise ValueError("evidence_unresolvable")
            seen.add(raw["story_plan_id"]);plan=plans[raw["story_plan_id"]]
            items.append({"story_plan_id":raw["story_plan_id"],"story_plan_title":plan["title"],"status":raw["status"],"explanation":self._text(raw["explanation"],600),"plan_source":self._clean_source({"source_type":"author_context","source_id":plan["id"]},maps,{"author_context"},project_id),"evidence":evidence})
        return {"summary":self._text(payload["summary"],400),"items":items}

    def execute(self,data:dict[str,Any])->dict[str,Any]:
        if not self.provider.available:return {"status":"failed","error_code":"provider_unavailable","retryable":True}
        request=self._request(data)
        response=None
        try:
            if request_prompt_and_budget(request)[1]>MAX_INPUT_BUDGET_UNITS:raise InputBudgetExceeded()
            response=self.provider.evaluate(request)
            if (response.input_tokens or 0)+(response.output_tokens or 0)>MAX_RUN_TOKENS:return {"status":"budget_paused","error_code":"budget_paused","retryable":True,**_aggregate([response])}
            analysis=self.validate(response.payload,data)
            return {"status":"completed","analysis":analysis,**_aggregate([response])}
        except InputBudgetExceeded:return {"status":"failed","error_code":"input_budget_exceeded","retryable":True}
        except ProviderUnavailable:return {"status":"failed","error_code":"provider_unavailable","retryable":True}
        except ProviderTimeout:return {"status":"timed_out","error_code":"provider_timeout","retryable":True}
        except ProviderInvalidJson as error:return {"status":"failed","error_code":"invalid_json","retryable":True,**_invalid_json_aggregate([],error)}
        except ProviderFailure:return {"status":"failed","error_code":"provider_error","retryable":True}
        except ValueError as error:return {"status":"failed","error_code":str(error),"retryable":True,**(_aggregate([response]) if response is not None else {})}


class MemoryInitializationEngine:
    """Validates every bounded batch in memory before one atomic persistence operation."""
    def __init__(self, provider: ProviderPort): self.provider=provider
    def provenance(self)->dict[str,str]:
        return {"provider_label":self.provider.label,"model_label":getattr(self.provider,"model_label",self.provider.label),"provider_api_format":getattr(self.provider,"api_format_label","injected-provider"),"prompt_version":MEMORY_PROMPT_VERSION,"schema_version":"memory-candidate-v1","chunking_method_version":SOURCE_CHUNK_METHOD_VERSION}
    def _request(self,sources:list[dict[str,Any]],source_revision:int)->dict[str,Any]:
        return {"task":"memory_initialization","source_revision":source_revision,"sources":sources,"controlled_predicates":list(CONTROLLED_PREDICATES),"output_schema":_memory_schema()}
    def chunking_method_version(self)->str:
        return SOURCE_CHUNK_METHOD_VERSION
    def _chunk(self,source:dict[str,Any],source_revision:int,ordinal:int,start:int,end:int)->dict[str,Any]:
        return {**source,"chunk_id":f"{source['id']}:r{source_revision}:chunk:{ordinal}","chunk_ordinal":ordinal,"chunk_start":start,"chunk_end":end,"body":source["body"][start:end]}
    def _maximum_chunk_end(self,source:dict[str,Any],source_revision:int,ordinal:int,start:int)->int:
        body=source["body"]; low=start+1; high=len(body); best=None
        while low<=high:
            end=(low+high)//2
            if request_prompt_and_budget(self._request([self._chunk(source,source_revision,ordinal,start,end)],source_revision))[1]<=MEMORY_BATCH_TARGET_BUDGET_UNITS:
                best=end; low=end+1
            else: high=end-1
        if best is None: raise InputBudgetExceeded()
        return best
    def _preferred_end(self,body:str,start:int,maximum:int,previous_end:int|None)->int:
        endings=[start+match.end() for match in re.finditer(r"(?:\r?\n)+|[。！？!?；;]",body[start:maximum])]
        eligible=[end for end in endings if previous_end is None or end>previous_end]
        return eligible[-1] if eligible else maximum
    def _source_chunks(self,source:dict[str,Any],source_revision:int)->list[dict[str,Any]]:
        if request_prompt_and_budget(self._request([source],source_revision))[1]<=MEMORY_BATCH_TARGET_BUDGET_UNITS:return [source]
        chunks=[]; body=source["body"]; start=0; ordinal=1; previous_end=None
        while start<len(body):
            maximum=self._maximum_chunk_end(source,source_revision,ordinal,start)
            end=self._preferred_end(body,start,maximum,previous_end)
            if end<=start or (previous_end is not None and end<=previous_end): raise InputBudgetExceeded()
            chunks.append(self._chunk(source,source_revision,ordinal,start,end))
            if end==len(body): break
            overlap=min(MAX_CHUNK_OVERLAP_CODEPOINTS,end-start-1)
            previous_end=end; start=end-overlap; ordinal+=1
        return chunks
    def chunk_plan(self,data:dict[str,Any])->list[dict[str,Any]]:
        ordered=sorted(data["sources"],key=lambda source:(source["chapter_number"],source["id"]))
        return [chunk for source in ordered for chunk in self._source_chunks(source,data["source_revision"])]
    def _batches(self,data:dict[str,Any])->list[dict[str,Any]]:
        batches=[]; current=[]
        for source in self.chunk_plan(data):
            candidate=current+[source]; request=self._request(candidate,data["source_revision"])
            if request_prompt_and_budget(request)[1] <= MEMORY_BATCH_TARGET_BUDGET_UNITS:
                current=candidate; continue
            if not current: raise InputBudgetExceeded()
            batches.append(self._request(current,data["source_revision"])); current=[source]
            if request_prompt_and_budget(self._request(current,data["source_revision"]))[1] > MEMORY_BATCH_TARGET_BUDGET_UNITS: raise InputBudgetExceeded()
        if current:batches.append(self._request(current,data["source_revision"]))
        return batches
    def execute(self,data:dict[str,Any])->dict[str,Any]:
        repair_attempts=0
        repair_events=[]
        normalization_counts={"trimmed_string":0,"memory_type_format":0,"extra_fields_removed":0}
        validated_batches=0
        candidates=[]
        def failure(error_code:str,failure_phase:str,failed_batch_ordinal:int|None,total_batches:int,metrics:dict[str,Any]|None=None,**extra:Any)->dict[str,Any]:
            return {"status":"failed","error_code":error_code,"retryable":True,"failure_phase":failure_phase,"failed_batch_ordinal":failed_batch_ordinal,"total_batches":total_batches,"schema_repair_attempts":repair_attempts,"repair_events":repair_events,"validated_batches":validated_batches,"staged_candidate_count":len(candidates),"normalization_count":sum(normalization_counts.values()),"normalization_kinds":{key:value for key,value in normalization_counts.items() if value},**(metrics or {}),**extra}
        if not self.provider.available:return failure("provider_unavailable","provider_preflight",None,0)
        try:batches=self._batches(data)
        except InputBudgetExceeded:return failure("input_budget_exceeded","batch_planning",None,0)
        results=[]
        total_batches=len(batches)
        for batch_ordinal,batch in enumerate(batches,start=1):
            request=batch
            active_repair_event=None
            batch_repair_attempts=0
            while True:
                try:
                    result=self.provider.evaluate(request)
                    if (result.input_tokens or 0)+(result.output_tokens or 0)>MAX_RUN_TOKENS:
                        if active_repair_event is not None:active_repair_event["result"]="provider_failed"
                        return failure("budget_paused","post_response_budget",batch_ordinal,total_batches,_aggregate(results+[result]))
                    results.append(result)
                except InputBudgetExceeded:
                    if active_repair_event is not None:active_repair_event["result"]="provider_failed"
                    return failure("input_budget_exceeded","provider_request",batch_ordinal,total_batches,_aggregate(results))
                except ProviderUnavailable:
                    if active_repair_event is not None:active_repair_event["result"]="provider_failed"
                    return failure("provider_unavailable","provider_request",batch_ordinal,total_batches,_aggregate(results))
                except ProviderTimeout:
                    if active_repair_event is not None:active_repair_event["result"]="provider_failed"
                    return failure("provider_timeout","provider_request",batch_ordinal,total_batches,_aggregate(results))
                except ProviderInvalidJson as error:
                    if active_repair_event is not None:active_repair_event["result"]="provider_failed"
                    return failure("invalid_json","post_response_decode",batch_ordinal,total_batches,_invalid_json_aggregate(results,error))
                except ProviderFailure:
                    if active_repair_event is not None:active_repair_event["result"]="provider_failed"
                    return failure("provider_error","provider_request",batch_ordinal,total_batches,_aggregate(results))
                try:
                    validated,normalizations=self._validate_with_normalization(result.payload,batch)
                except MemoryCandidateValidationError as error:
                    error_code=error.code
                    if active_repair_event is not None:
                        active_repair_event["result"]="failed"
                        active_repair_event["final_reason_code"]=error_code
                        active_repair_event=None
                    if error_code in MEMORY_REPAIRABLE_ERRORS and repair_attempts<MEMORY_SCHEMA_REPAIR_MAX_ATTEMPTS and batch_repair_attempts<MEMORY_SCHEMA_REPAIR_MAX_PER_BATCH:
                        repair_attempts+=1
                        batch_repair_attempts+=1
                        active_repair_event={"batch_ordinal":batch_ordinal,"attempt":repair_attempts,"batch_attempt":batch_repair_attempts,"reason_code":error_code,"result":"pending",**({"field":error.field} if error.field else {}),**({"candidate_ordinal":error.candidate_ordinal} if error.candidate_ordinal else {})}
                        repair_events.append(active_repair_event)
                        request={**batch,"schema_repair":{"reason_code":error_code,"attempt":batch_repair_attempts,"global_attempt":repair_attempts,**({"field":error.field} if error.field else {}),**({"candidate_ordinal":error.candidate_ordinal} if error.candidate_ordinal else {})}}
                        continue
                    return failure(error_code,"post_response_validation",batch_ordinal,total_batches,_aggregate(results),**error.safe_context())
                if active_repair_event is not None:active_repair_event["result"]="succeeded"
                for kind,count in normalizations.items():normalization_counts[kind]+=count
                candidates.extend(validated)
                validated_batches+=1
                break
        deduped=[]; seen=set()
        for item in candidates:
            identity=(item["memory_type"],item["subject"],item["predicate"],item["value"],item["source_span_id"])
            if identity not in seen: seen.add(identity); deduped.append(item)
        if not deduped:return failure("schema_invalid","post_aggregation",None,total_batches,_aggregate(results))
        return {"status":"completed","candidates":deduped,"total_batches":total_batches,"schema_repair_attempts":repair_attempts,"repair_events":repair_events,"validated_batches":validated_batches,"staged_candidate_count":len(candidates),"normalization_count":sum(normalization_counts.values()),"normalization_kinds":{key:value for key,value in normalization_counts.items() if value},**_aggregate(results)}
    def validate(self,payload:Any,data:dict[str,Any])->list[dict[str,Any]]:
        return self._validate_with_normalization(payload,data)[0]
    def _validate_with_normalization(self,payload:Any,data:dict[str,Any])->tuple[list[dict[str,Any]],dict[str,int]]:
        if not isinstance(payload,dict) or set(payload)!={"candidates"}:raise MemoryCandidateValidationError("top_level_shape_invalid")
        if not isinstance(payload["candidates"],list):raise MemoryCandidateValidationError("candidate_collection_invalid")
        if len(payload["candidates"])>MAX_MEMORY_CANDIDATES_PER_BATCH:raise MemoryCandidateValidationError("candidate_count_invalid")
        if not payload["candidates"]:raise MemoryCandidateValidationError("empty_candidates")
        sources={item["id"]:item for item in data["sources"]}; candidates=[]; seen=set()
        normalizations={"trimmed_string":0,"memory_type_format":0,"extra_fields_removed":0}
        required=set(MEMORY_CANDIDATE_FIELDS)
        for candidate_ordinal,item in enumerate(payload["candidates"],start=1):
            if not isinstance(item,dict):raise MemoryCandidateValidationError("candidate_fields_invalid",candidate_ordinal=candidate_ordinal)
            missing=required-set(item)
            if missing:raise MemoryCandidateValidationError("candidate_fields_invalid",field=sorted(missing)[0],candidate_ordinal=candidate_ordinal)
            extra=set(item)-required
            if extra:normalizations["extra_fields_removed"]+=len(extra)
            values={key:item[key] for key in MEMORY_CANDIDATE_FIELDS}
            for field,value in values.items():
                if not isinstance(value,str):raise MemoryCandidateValidationError("required_field_type_invalid",field=field,candidate_ordinal=candidate_ordinal)
                stripped=value.strip()
                if not stripped:raise MemoryCandidateValidationError("required_field_blank",field=field,candidate_ordinal=candidate_ordinal)
                if stripped!=value:normalizations["trimmed_string"]+=1
                values[field]=stripped
            memory_type=values["memory_type"].lower().replace("-","_")
            if memory_type not in ALLOWED_MEMORY_TYPE:raise MemoryCandidateValidationError("memory_type_invalid",field="memory_type",candidate_ordinal=candidate_ordinal)
            if memory_type!=values["memory_type"]:normalizations["memory_type_format"]+=1
            values["memory_type"]=memory_type
            if len(values["subject"])>80:raise MemoryCandidateValidationError("candidate_length_invalid",field="subject",candidate_ordinal=candidate_ordinal)
            if len(values["predicate"])>80:raise MemoryCandidateValidationError("candidate_length_invalid",field="predicate",candidate_ordinal=candidate_ordinal)
            if len(values["value"])>240:raise MemoryCandidateValidationError("candidate_length_invalid",field="value",candidate_ordinal=candidate_ordinal)
            source=sources.get(values["source_span_id"])
            if not source or source["chapter_id"]!=values["chapter_id"]:raise MemoryCandidateValidationError("evidence_unresolvable",field="source_span_id",candidate_ordinal=candidate_ordinal)
            identity=(values["memory_type"],values["subject"],values["predicate"],values["value"],values["source_span_id"])
            if identity in seen:continue
            seen.add(identity); candidates.append(values)
        return candidates,normalizations


class MemoryDeltaEngine(MemoryInitializationEngine):
    """A separate provider contract for one append-only source revision."""
    def provenance(self)->dict[str,str]:
        return {"provider_label":self.provider.label,"model_label":getattr(self.provider,"model_label",self.provider.label),"prompt_version":"memory-delta-v3-fact-lifecycle","schema_version":"memory-delta-candidate-v2","retrieval_method_version":RETRIEVAL_METHOD_VERSION}

    def _related_memory(self,data:dict[str,Any])->list[dict[str,Any]]:
        terms=_claim_terms("\n".join(str(source.get("body","")) for source in data["sources"])); ranked=[]
        for item in data["memory"]:
            text=" ".join(str(item.get(key,"")) for key in ("subject","predicate","value"))
            ranked.append((_relevance_score(terms,text),item))
        return [item for _,item in sorted(ranked,key=lambda row:(-row[0],_memory_sort_key(row[1])))[:MEMORY_DELTA_RELATED_MEMORY_LIMIT]]

    def _bounded_sources(self,data:dict[str,Any])->list[dict[str,Any]]:
        ordered=sorted(data["sources"],key=lambda source:(int(source.get("chapter_number",0)),str(source.get("id",""))))
        return [{**source,"body":str(source.get("body",""))[:MEMORY_DELTA_SOURCE_EXCERPT_CODEPOINTS]} for source in ordered[:MEMORY_DELTA_SOURCE_LIMIT]]

    def _request(self, data:dict[str,Any])->dict[str,Any]:
        sources=self._bounded_sources(data)
        return {"task":"memory_delta","source_revision":data["source_revision"],"sources":sources,"memory":self._related_memory({**data,"sources":sources}),"controlled_predicates":list(CONTROLLED_PREDICATES),"output_schema":_memory_delta_schema()}

    def validate(self,payload:Any,data:dict[str,Any])->list[dict[str,Any]]:
        if not isinstance(payload,dict) or set(payload)!={"candidates"} or not isinstance(payload["candidates"],list):raise ValueError("schema_invalid")
        if len(payload["candidates"])>MAX_MEMORY_CANDIDATES_PER_BATCH:raise ValueError("candidate_count_invalid")
        sources={item["id"]:item for item in data["sources"]}; memory={item["id"]:item for item in data["memory"]}
        required=set(MEMORY_DELTA_CANDIDATE_FIELDS); candidates=[]; affected_seen=set(); identities=set()
        active_keys={
            (str(item["memory_type"]),str(item["subject"]).strip(),str(item["predicate"]).strip()):item["id"]
            for item in data["memory"]
        }
        for item in payload["candidates"]:
            if not isinstance(item,dict) or set(item)!=required:raise ValueError("candidate_fields_invalid")
            change_kind=item["change_kind"]
            if change_kind not in {"new_fact","changed_fact","invalidated_fact"}:raise ValueError("change_kind_invalid")
            values={}
            for field in ("memory_type","subject","predicate","value","chapter_id","source_span_id"):
                value=item[field]
                if not isinstance(value,str) or not value.strip():raise ValueError("candidate_fields_invalid")
                values[field]=value.strip()
            if values["memory_type"] not in ALLOWED_MEMORY_TYPE:raise ValueError("memory_type_invalid")
            if values["predicate"] not in CONTROLLED_PREDICATES:raise ValueError("predicate_invalid")
            if len(values["subject"])>80 or len(values["predicate"])>80 or len(values["value"])>240:raise ValueError("candidate_length_invalid")
            source=sources.get(values["source_span_id"])
            if not source or source["chapter_id"]!=values["chapter_id"]:raise ValueError("evidence_unresolvable")
            affected=item["affected_memory_id"]
            reason=item["invalidation_reason"]
            if change_kind=="new_fact":
                if affected is not None:raise ValueError("affected_memory_invalid")
                if reason is not None:raise ValueError("invalidation_reason_invalid")
                if (values["memory_type"],values["subject"],values["predicate"]) in active_keys:raise ValueError("candidate_conflict")
            else:
                if not isinstance(affected,str) or not affected.strip() or affected.strip() not in memory:raise ValueError("affected_memory_unresolvable")
                affected=affected.strip()
                if affected in affected_seen:raise ValueError("duplicate_candidate")
                affected_seen.add(affected); before=memory[affected]
                before_fact={field:str(before[field]).strip() for field in ("memory_type","subject","predicate","value")}
                if change_kind=="changed_fact":
                    if reason is not None:raise ValueError("invalidation_reason_invalid")
                    if all(values[field]==before_fact[field] for field in before_fact):raise ValueError("candidate_conflict")
                    target_key=(values["memory_type"],values["subject"],values["predicate"])
                    if target_key in active_keys and active_keys[target_key]!=affected:raise ValueError("candidate_conflict")
                else:
                    if not isinstance(reason,str) or not reason.strip() or len(reason.strip())>240:raise ValueError("invalidation_reason_invalid")
                    reason=reason.strip()
                    if any(values[field]!=before_fact[field] for field in before_fact):raise ValueError("candidate_conflict")
            identity=(change_kind,affected,values["memory_type"],values["subject"],values["predicate"],values["value"],values["source_span_id"])
            if identity in identities:raise ValueError("duplicate_candidate")
            identities.add(identity)
            candidates.append({"change_kind":change_kind,"affected_memory_id":affected,**values,"invalidation_reason":reason})
        return candidates

    def execute(self,data:dict[str,Any])->dict[str,Any]:
        if not self.provider.available:return {"status":"failed","error_code":"provider_unavailable","retryable":True}
        request=self._request(data)
        if request_prompt_and_budget(request)[1] > MAX_INPUT_BUDGET_UNITS:return {"status":"failed","error_code":"input_budget_exceeded","retryable":True}
        try:
            result=self.provider.evaluate(request)
            if (result.input_tokens or 0)+(result.output_tokens or 0)>MAX_RUN_TOKENS:return {"status":"failed","error_code":"budget_paused","retryable":True,**_aggregate([result])}
            candidates=self.validate(result.payload,{"sources":request["sources"],"memory":request["memory"]})
            retrieval={"method_version":RETRIEVAL_METHOD_VERSION,"selected_source_span_ids":[item["id"] for item in request["sources"]],"selected_memory_ids":[item["id"] for item in request["memory"]],"counts":{"source_spans":{"available":len(data["sources"]),"selected":len(request["sources"])},"confirmed_memory":{"available":len(data["memory"]),"selected":len(request["memory"])}},"truncated":{"source_spans":len(request["sources"])<len(data["sources"]),"confirmed_memory":len(request["memory"])<len(data["memory"])}}
            return {"status":"completed","candidates":candidates,"retrieved_memory_count":len(request["memory"]),"retrieval_method_version":RETRIEVAL_METHOD_VERSION,"retrieval":retrieval,**_aggregate([result])}
        except ProviderUnavailable:return {"status":"failed","error_code":"provider_unavailable","retryable":True}
        except ProviderTimeout:return {"status":"timed_out","error_code":"provider_timeout","retryable":True}
        except ProviderInvalidJson as error:return {"status":"failed","error_code":"invalid_json","retryable":True,**_invalid_json_aggregate([],error)}
        except ProviderFailure:return {"status":"failed","error_code":"provider_error","retryable":True}
        except ValueError as error:return {"status":"failed","error_code":str(error),"retryable":True}
