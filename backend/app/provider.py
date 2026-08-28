from __future__ import annotations
import json,os,time
from dataclasses import dataclass
from typing import Any,Protocol
import httpx
class ProviderUnavailable(Exception):pass
class ProviderTimeout(Exception):pass
class ProviderFailure(Exception):pass
class ProviderInvalidJson(Exception):pass
@dataclass(frozen=True)
class ProviderResult: payload:Any; input_tokens:int|None=None; output_tokens:int|None=None; cost_cny:float|None=None; latency_ms:int|None=None
def parse_json_content(content: Any) -> Any:
 if not isinstance(content,str): return content
 candidate=content.strip()
 lines=candidate.splitlines()
 if len(lines)>=2 and lines[0].strip().lower() in {"```","```json"} and lines[-1].strip()=="```":
  candidate="\n".join(lines[1:-1]).strip()
 return json.loads(candidate)
class ProviderPort(Protocol):
 label:str
 @property
 def available(self)->bool:...
 def evaluate(self,request:dict[str,Any])->ProviderResult:...
class DeepSeekProvider:
 label="deepseek"; max_output_tokens=1200; timeout_seconds=30; max_retries=1
 def __init__(self,client_factory=None):
  self.model=os.getenv("CONTINUITY_MODEL","");self.base_url=os.getenv("CONTINUITY_BASE_URL","");self.api_key=os.getenv("CONTINUITY_API_KEY","");self.enabled=os.getenv("CONTINUITY_PROVIDER","").lower()=="deepseek";self._factory=client_factory or (lambda:httpx.Client(timeout=httpx.Timeout(self.timeout_seconds)))
 @property
 def model_label(self):return self.model or "unconfigured"
 @property
 def available(self):return bool(self.enabled and self.model and self.base_url and self.api_key)
 def evaluate(self,request):
  if not self.available:raise ProviderUnavailable()
  prompt=json.dumps({"task":"Review continuity only. Return exactly one JSON object with exactly one top-level key, issues. Do not use Markdown or include any other top-level key.","rules":["Decide every current claim before emitting output: direct contradiction means conflict; material that neither supports nor refutes the concrete claim means insufficient_evidence; material that supports the claim or reveals no continuity risk means omit that claim from issues.","Every emitted issue must use one claim_span_id from current_claims. Use only conflict or insufficient_evidence for emitted issues; never emit a no_conflict issue.","Emit conflict only when the retrieved material directly contradicts the target claim. A conflict must contain the minimal necessary set of one or more direct Evidence objects copied from that claim's allowed_evidence; every item must use relation contradicts and sufficiency sufficient. Do not add background-only Evidence or infer a contradiction from a missing detail.","Emit insufficient_evidence when the retrieved material neither supports nor contradicts the target claim, including an unsupported specific name, number, place, or time. It must contain evidence: [], no proposed_memory_change, and a short reviewable explanation. Do not turn an unknown detail into a conflict.","Every emitted issue must include a valid category, severity, and non-empty explanation. Category boundaries: attribute is an intrinsic or durable property of one entity; object_state is the condition, location, availability, or possession of a named object; relationship is a bond, role, authority, or kinship between entities; character_knowledge is what a character knows, believes, or has been told. Use timeline for order or date, world_rule for systemic constraints, location_action for place or action continuity, and event_status for whether an event occurred or remains open.","Omit proposed_memory_change unless the conflict and its direct Evidence fully ground it: operation is add or replace, memory_type is static_canon, dynamic_state, event_timeline, character_knowledge, or open_thread, subject/predicate/value are non-empty strings, and replace uses a known affected_memory_id.","Never cite IDs outside each claim.allowed_evidence."],"draft":request["draft"],"current_claims":[{"id":x["id"],"text":x["text"],"allowed_evidence":[{"id":s["id"],"chapter_id":s["chapter_id"],"excerpt":s["body"]} for s in x["allowed_evidence"]]} for x in request["claims"]],"memory":request["memory"],"output_schema":request["output_schema"]},ensure_ascii=False,separators=(",",":"))
  body={"model":self.model,"messages":[{"role":"user","content":prompt}],"response_format":{"type":"json_object"},"thinking":{"type":"disabled"},"temperature":0,"max_tokens":self.max_output_tokens}
  started=time.perf_counter()
  for attempt in range(self.max_retries+1):
   try:
    with self._factory() as client:r=client.post(self.base_url.rstrip("/")+"/chat/completions",headers={"Authorization":f"Bearer {self.api_key}","Content-Type":"application/json"},json=body);r.raise_for_status();raw=r.json();parsed=parse_json_content(raw["choices"][0]["message"]["content"]);usage=raw.get("usage",{});return ProviderResult(parsed,usage.get("prompt_tokens"),usage.get("completion_tokens"),None,int((time.perf_counter()-started)*1000))
   except httpx.TimeoutException as e:
    if attempt==self.max_retries:raise ProviderTimeout() from e
   except json.JSONDecodeError as e:raise ProviderInvalidJson() from e
   except (httpx.HTTPError,ValueError,KeyError,TypeError) as e:raise ProviderFailure() from e
