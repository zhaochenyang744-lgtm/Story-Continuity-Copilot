from __future__ import annotations

import re
from typing import Any

from .memory_contract import CONTROLLED_PREDICATES
from .provider import InputBudgetExceeded, MAX_INPUT_BUDGET_UNITS, MAX_MEMORY_CANDIDATES_PER_BATCH, MEMORY_BATCH_TARGET_BUDGET_UNITS, ProviderFailure, ProviderInvalidJson, ProviderPort, ProviderTimeout, ProviderUnavailable, request_prompt_and_budget

ALLOWED_STATUS={"conflict","insufficient_evidence"}
ALLOWED_CATEGORY={"attribute","location_action","timeline","character_knowledge","object_state","relationship","world_rule","event_status"}
ALLOWED_SEVERITY={"low","medium","high"}
ALLOWED_MEMORY_TYPE={"static_canon","dynamic_state","event_timeline","character_knowledge","open_thread"}
MAX_RUN_TOKENS=8000
PROMPT_VERSION="continuity-review-v8-bounded-evidence"
MEMORY_PROMPT_VERSION="memory-initialization-v8-pro-two-repair"
RETRIEVAL_METHOD_VERSION="bounded-lexical-v4-longform"
RELATED_MEMORY_LIMIT=15
CONTINUITY_EVIDENCE_LIMIT=3
CONTINUITY_EVIDENCE_EXCERPT_CODEPOINTS=500
MEMORY_DELTA_RELATED_MEMORY_LIMIT=20
SOURCE_CHUNK_METHOD_VERSION="source-chunk-v4-5800"
MAX_CHUNK_OVERLAP_CODEPOINTS=200
MEMORY_SCHEMA_REPAIR_MAX_ATTEMPTS=5
MEMORY_SCHEMA_REPAIR_MAX_PER_BATCH=2
MEMORY_CANDIDATE_FIELDS=("memory_type","subject","predicate","value","chapter_id","source_span_id")
MEMORY_REPAIRABLE_ERRORS={"top_level_shape_invalid","candidate_collection_invalid","candidate_count_invalid","empty_candidates","candidate_fields_invalid","memory_type_invalid","required_field_type_invalid","required_field_blank","candidate_length_invalid","evidence_unresolvable"}


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


def _continuity_schema() -> dict[str, Any]:
    return {"issues":[{"claim_span_id":"current claim id","status":"conflict|insufficient_evidence","category":"allowed category","severity":"low|medium|high","explanation":"non-empty short reviewable conclusion","evidence":[{"chapter_id":"allowed chapter id","span_id":"allowed span id","relation":"supports|contradicts|context","sufficiency":"sufficient|insufficient","related_memory_ids":["known memory id"]}],"proposed_memory_change":{"operation":"add|replace","memory_type":"allowed memory type","subject":"string","predicate":"string","value":"string","affected_memory_id":"required for replace only"}}]}


def _memory_schema() -> dict[str, Any]:
    return {"candidates":[{"memory_type":"allowed memory type","subject":"string","predicate":"string","value":"string","chapter_id":"source chapter id","source_span_id":"supplied source span id"}]}


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
        return {"provider_label":self.provider.label,"model_label":getattr(self.provider,"model_label",self.provider.label),"prompt_version":PROMPT_VERSION,"schema_version":"continuity-issue-v3","retrieval_method_version":RETRIEVAL_METHOD_VERSION}

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

    def execute(self,data:dict[str,Any])->dict[str,Any]:
        if not self.provider.available:return {"status":"failed","error_code":"provider_unavailable","retryable":True}
        try:batches=self._batches(data)
        except InputBudgetExceeded:return {"status":"failed","error_code":"input_budget_exceeded","retryable":True}
        results=[]; issues=[]
        retrieval_traces=[{"claim_id":claim["id"],"returned_span_ids":[span["id"] for span in claim["allowed_evidence"]]} for batch in batches for claim in batch["claims"]]
        try:
            for batch in batches:
                result=self.provider.evaluate(batch)
                if (result.input_tokens or 0)+(result.output_tokens or 0)>MAX_RUN_TOKENS:return {"status":"budget_paused","error_code":"budget_paused","retryable":True,**_aggregate(results+[result])}
                results.append(result)
                issues.extend(self.validate(result.payload,batch))
        except InputBudgetExceeded:return {"status":"failed","error_code":"input_budget_exceeded","retryable":True,**_aggregate(results)}
        except ProviderUnavailable:return {"status":"failed","error_code":"provider_unavailable","retryable":True,**_aggregate(results)}
        except ProviderTimeout:return {"status":"timed_out","error_code":"provider_timeout","retryable":True,**_aggregate(results)}
        except ProviderInvalidJson as error:return {"status":"failed","error_code":"invalid_json","retryable":True,**_invalid_json_aggregate(results,error)}
        except ProviderFailure:return {"status":"failed","error_code":"provider_error","retryable":True,**_aggregate(results)}
        except ValueError as error:return {"status":"failed","error_code":str(error),"retryable":True,**_aggregate(results)}
        order={claim["id"]:index for index,claim in enumerate(data["claims"])}
        if len({issue["claim_span_id"] for issue in issues}) != len(issues): return {"status":"failed","error_code":"schema_invalid","retryable":True,**_aggregate(results)}
        return {"status":"completed","issues":sorted(issues,key=lambda item:order[item["claim_span_id"]]),"retrieval_traces":retrieval_traces,"retrieval_method_version":RETRIEVAL_METHOD_VERSION,**_aggregate(results)}

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
                cleaned.append({"chapter_id":s["chapter_id"],"span_id":s["id"],"excerpt":s.get("prompt_excerpt",s["body"]),"relation":ev["relation"],"sufficiency":ev["sufficiency"],"related_memory_ids":ev.get("related_memory_ids",[])})
            change=raw.get("proposed_memory_change")
            if change is not None:
                required={"memory_type","subject","predicate","value","operation"}
                if (not isinstance(change,dict) or not required<=set(change) or change["memory_type"] not in ALLOWED_MEMORY_TYPE or change["operation"] not in {"add","replace"} or any(not isinstance(change[key],str) or not change[key].strip() for key in ("subject","predicate","value")) or (change["operation"]=="add" and change.get("affected_memory_id") is not None) or (change["operation"]=="replace" and change.get("affected_memory_id") not in mem) or raw["status"]!="conflict"):raise ValueError("schema_invalid")
            output.append({"claim_span_id":raw["claim_span_id"],"status":raw["status"],"category":raw["category"],"severity":raw["severity"],"evidence_status":"sufficient" if evs else "insufficient","explanation":explanation.strip()[:500],"evidence":cleaned,"proposed_memory_change":change})
        return output


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
        return {"provider_label":self.provider.label,"model_label":getattr(self.provider,"model_label",self.provider.label),"prompt_version":"memory-delta-v2-bounded-retrieval","schema_version":"memory-delta-candidate-v1","retrieval_method_version":RETRIEVAL_METHOD_VERSION}

    def _related_memory(self,data:dict[str,Any])->list[dict[str,Any]]:
        terms=_claim_terms("\n".join(str(source.get("body","")) for source in data["sources"])); ranked=[]
        for item in data["memory"]:
            text=" ".join(str(item.get(key,"")) for key in ("subject","predicate","value"))
            ranked.append((_relevance_score(terms,text),item))
        return [item for _,item in sorted(ranked,key=lambda row:(-row[0],_memory_sort_key(row[1])))[:MEMORY_DELTA_RELATED_MEMORY_LIMIT]]

    def _request(self, data:dict[str,Any])->dict[str,Any]:
        return {"task":"memory_delta","source_revision":data["source_revision"],"sources":data["sources"],"memory":self._related_memory(data),"controlled_predicates":list(CONTROLLED_PREDICATES),"output_schema":_memory_schema()}

    def validate(self,payload:Any,data:dict[str,Any])->list[dict[str,Any]]:
        try:return super().validate(payload,data)
        except ValueError as error:
            if str(error)=="evidence_unresolvable":raise
            raise ValueError("schema_invalid") from None

    def execute(self,data:dict[str,Any])->dict[str,Any]:
        if not self.provider.available:return {"status":"failed","error_code":"provider_unavailable","retryable":True}
        request=self._request(data)
        if request_prompt_and_budget(request)[1] > MAX_INPUT_BUDGET_UNITS:return {"status":"failed","error_code":"input_budget_exceeded","retryable":True}
        try:
            result=self.provider.evaluate(request)
            if (result.input_tokens or 0)+(result.output_tokens or 0)>MAX_RUN_TOKENS:return {"status":"failed","error_code":"budget_paused","retryable":True,**_aggregate([result])}
            candidates=self.validate(result.payload,{"sources":data["sources"]})
            return {"status":"completed","candidates":candidates,"retrieved_memory_count":len(request["memory"]),"retrieval_method_version":RETRIEVAL_METHOD_VERSION,**_aggregate([result])}
        except ProviderUnavailable:return {"status":"failed","error_code":"provider_unavailable","retryable":True}
        except ProviderTimeout:return {"status":"timed_out","error_code":"provider_timeout","retryable":True}
        except ProviderInvalidJson as error:return {"status":"failed","error_code":"invalid_json","retryable":True,**_invalid_json_aggregate([],error)}
        except ProviderFailure:return {"status":"failed","error_code":"provider_error","retryable":True}
        except ValueError as error:return {"status":"failed","error_code":str(error),"retryable":True}
