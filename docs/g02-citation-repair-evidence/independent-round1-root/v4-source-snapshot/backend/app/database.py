from __future__ import annotations

import hashlib, json, sqlite3, uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AppPaths, ProtectedPathError
from .seed_data import CHAPTERS, DRAFT, MEMORY_RECORDS, PROJECT, SEED_ORIGIN

class DomainError(ValueError):
    def __init__(self, code: str, status: int = 400, retryable: bool = False, details: dict[str, Any] | None = None):
        super().__init__(code); self.code, self.status, self.retryable, self.details = code, status, retryable, details

def now() -> str: return datetime.now(timezone.utc).isoformat()
def digest(value: Any) -> str: return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS seed_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,title TEXT NOT NULL,summary TEXT NOT NULL,data_origin TEXT NOT NULL,current_memory_version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS chapters(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,chapter_number INTEGER NOT NULL,title TEXT NOT NULL,summary TEXT NOT NULL,UNIQUE(project_id,chapter_number));
CREATE TABLE IF NOT EXISTS source_spans(id TEXT PRIMARY KEY,chapter_id TEXT NOT NULL,label TEXT NOT NULL,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,chapter_number INTEGER NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,revision INTEGER NOT NULL,status TEXT NOT NULL,saved_at TEXT NOT NULL,parent_revision INTEGER,edit_context TEXT,body_checksum TEXT);
CREATE TABLE IF NOT EXISTS draft_revisions(draft_id TEXT NOT NULL,revision INTEGER NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,body_checksum TEXT NOT NULL,parent_revision INTEGER,edit_context TEXT,saved_at TEXT NOT NULL,PRIMARY KEY(draft_id,revision));
CREATE TABLE IF NOT EXISTS memory_versions(project_id TEXT NOT NULL,version INTEGER NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,parent_version INTEGER,PRIMARY KEY(project_id,version));
CREATE TABLE IF NOT EXISTS memory_records(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,version INTEGER NOT NULL,memory_type TEXT NOT NULL,subject TEXT NOT NULL,predicate TEXT NOT NULL,value TEXT NOT NULL,source_span_id TEXT NOT NULL,review_status TEXT NOT NULL,valid_from INTEGER,valid_to INTEGER);
CREATE TABLE IF NOT EXISTS reset_audit(reset_id TEXT PRIMARY KEY,idempotency_key TEXT NOT NULL UNIQUE,request_fingerprint TEXT NOT NULL,reason TEXT NOT NULL,completed_at TEXT NOT NULL,response_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS write_idempotency(operation TEXT NOT NULL,idempotency_key TEXT NOT NULL,fingerprint TEXT NOT NULL,response_json TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(operation,idempotency_key));
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,draft_id TEXT NOT NULL,source_revision INTEGER NOT NULL,status TEXT NOT NULL,stage TEXT NOT NULL,provider_label TEXT NOT NULL,latency_ms INTEGER,input_tokens INTEGER,output_tokens INTEGER,cost_cny REAL,error_code TEXT,retryable INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,completed_at TEXT);
CREATE TABLE IF NOT EXISTS run_stages(run_id TEXT NOT NULL,stage TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(run_id,stage));
CREATE TABLE IF NOT EXISTS issues(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,claim_span_id TEXT NOT NULL,status TEXT NOT NULL,category TEXT NOT NULL,severity TEXT NOT NULL,evidence_status TEXT NOT NULL,explanation TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evidence(id TEXT PRIMARY KEY,issue_id TEXT NOT NULL,chapter_id TEXT NOT NULL,span_id TEXT NOT NULL,excerpt TEXT NOT NULL,relation TEXT NOT NULL,sufficiency TEXT NOT NULL,related_memory_ids TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY,issue_id TEXT NOT NULL,run_id TEXT NOT NULL,decision TEXT NOT NULL,note TEXT,source_revision INTEGER NOT NULL,resulting_revision INTEGER,lineage_status TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(issue_id,source_revision));
CREATE TABLE IF NOT EXISTS change_sets(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,run_id TEXT NOT NULL,source_run_revision INTEGER NOT NULL,resolved_revision INTEGER NOT NULL,lineage_status TEXT NOT NULL,base_version INTEGER NOT NULL,target_version INTEGER NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,committed_at TEXT);
CREATE TABLE IF NOT EXISTS change_set_items(id TEXT PRIMARY KEY,change_set_id TEXT NOT NULL,operation TEXT NOT NULL,before_json TEXT,after_json TEXT NOT NULL,source_ids TEXT NOT NULL,decision_ids TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS commit_audits(id TEXT PRIMARY KEY,change_set_id TEXT NOT NULL,status TEXT NOT NULL,accepted_item_ids TEXT NOT NULL,rejected_item_ids TEXT NOT NULL,note TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS run_claims(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,ordinal INTEGER NOT NULL,text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS retrieval_traces(run_id TEXT NOT NULL,claim_id TEXT NOT NULL,query_terms TEXT NOT NULL,returned_span_ids TEXT NOT NULL,method_version TEXT NOT NULL,PRIMARY KEY(run_id,claim_id));
"""

class DemoDatabase:
    def __init__(self, paths: AppPaths): self.paths=paths; self.paths.validate_database_target()
    def _connect(self):
        self.paths.prepare_runtime(); c=sqlite3.connect(self.paths.database_path); c.row_factory=sqlite3.Row; c.execute("PRAGMA foreign_keys=ON"); return c
    @contextmanager
    def connection(self):
        c=self._connect()
        try: yield c; c.commit()
        except Exception: c.rollback(); raise
        finally: c.close()
    def initialize(self):
        with self.connection() as c:
            c.executescript(SCHEMA); self._migrate(c)
            if not c.execute("SELECT COUNT(*) FROM projects").fetchone()[0]: self._seed(c)
    def _migrate(self,c):
        for table, columns in {"drafts":{"parent_revision":"INTEGER","edit_context":"TEXT","body_checksum":"TEXT"},"memory_versions":{"parent_version":"INTEGER"},"memory_records":{"valid_from":"INTEGER","valid_to":"INTEGER","source_claim_id":"TEXT"}}.items():
            have={r[1] for r in c.execute(f"PRAGMA table_info({table})")}
            for name,typ in columns.items():
                if name not in have: c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
        for table, columns in {"issues":{"proposed_change_json":"TEXT"},"change_set_items":{"review_status":"TEXT"}}.items():
            have={r[1] for r in c.execute(f"PRAGMA table_info({table})")}
            for name,typ in columns.items():
                if name not in have: c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
        c.execute("INSERT OR IGNORE INTO schema_migrations VALUES (2,?)",(now(),)); c.execute("INSERT OR IGNORE INTO schema_migrations VALUES (3,?)",(now(),)); c.execute("INSERT OR IGNORE INTO schema_migrations VALUES (4,?)",(now(),))
        for row in c.execute("SELECT id,title,body,revision,status,saved_at,parent_revision,edit_context,body_checksum FROM drafts").fetchall():
            checksum=row["body_checksum"] or digest(row["body"]); c.execute("UPDATE drafts SET body_checksum=? WHERE id=?",(checksum,row["id"])); c.execute("INSERT OR IGNORE INTO draft_revisions VALUES (?,?,?,?,?,?,?,?)",(row["id"],row["revision"],row["title"],row["body"],checksum,row["parent_revision"],row["edit_context"],row["saved_at"]))
    def _seed(self,c):
        t=now(); c.execute("INSERT INTO seed_metadata VALUES (?,?)",("provenance",json.dumps(SEED_ORIGIN,ensure_ascii=False))); c.execute("INSERT INTO projects VALUES (?,?,?,?,4)",(PROJECT["id"],PROJECT["title"],PROJECT["summary"],PROJECT["data_origin"]))
        for cid,num,title,summary,spans in CHAPTERS:
            c.execute("INSERT INTO chapters VALUES (?,?,?,?,?)",(cid,PROJECT["id"],num,title,summary))
            for sid,label,body in spans: c.execute("INSERT INTO source_spans VALUES (?,?,?,?)",(sid,cid,label,body))
        checksum=digest(DRAFT["body"]); c.execute("INSERT INTO drafts VALUES (?,?,?,?,?,?,?,?,?,?,?)",(DRAFT["id"],PROJECT["id"],DRAFT["chapter_number"],DRAFT["title"],DRAFT["body"],1,"saved",t,None,None,checksum)); c.execute("INSERT INTO draft_revisions VALUES (?,?,?,?,?,?,?,?)",(DRAFT["id"],1,DRAFT["title"],DRAFT["body"],checksum,None,None,t)); c.execute("INSERT INTO memory_versions VALUES (?,?,?,?,?)",(PROJECT["id"],4,"current",t,None))
        for rid,typ,sub,pred,val,span in MEMORY_RECORDS: c.execute("INSERT INTO memory_records(id,project_id,version,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to,source_claim_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)",(rid,PROJECT["id"],4,typ,sub,pred,val,span,"author_confirmed",1,None))
    def _idem(self,c,operation,key,payload,build):
        fp=digest(payload); old=c.execute("SELECT fingerprint,response_json FROM write_idempotency WHERE operation=? AND idempotency_key=?",(operation,key)).fetchone()
        if old:
            if old["fingerprint"]!=fp: raise DomainError("idempotency_conflict",409)
            return json.loads(old["response_json"])
        response=build(); c.execute("INSERT INTO write_idempotency VALUES (?,?,?,?,?)",(operation,key,fp,json.dumps(response,ensure_ascii=False),now())); return response
    def project(self):
        self.initialize()
        with self.connection() as c:
            p=c.execute("SELECT * FROM projects WHERE id=?",(PROJECT["id"],)).fetchone(); d=c.execute("SELECT id,chapter_number,revision,status FROM drafts WHERE id=?",(DRAFT["id"],)).fetchone(); last=c.execute("SELECT id,status,created_at FROM runs ORDER BY created_at DESC LIMIT 1").fetchone()
            return {"project_id":p["id"],"title":p["title"],"summary":p["summary"],"chapter_count":c.execute("SELECT COUNT(*) FROM chapters").fetchone()[0],"current_memory_version":p["current_memory_version"],"current_draft":dict(d),"latest_run":({"run_id":last["id"],"status":last["status"],"created_at":last["created_at"]} if last else None),"data_origin":p["data_origin"]}
    def chapters(self,chapter_id=None,excerpt=False):
        self.initialize()
        with self.connection() as c:
            rows=c.execute("SELECT * FROM chapters"+(" WHERE id=?" if chapter_id else " ORDER BY chapter_number"),(chapter_id,) if chapter_id else ()).fetchall()
            if chapter_id and not rows: raise DomainError("project_or_chapter_not_found",404)
            result=[]
            for r in rows:
                x={"id":r["id"],"number":r["chapter_number"],"title":r["title"],"summary":r["summary"]}
                if excerpt:x["source_spans"]=[{"span_id":s["id"],"label":s["label"],"text_excerpt":s["body"]} for s in c.execute("SELECT * FROM source_spans WHERE chapter_id=?",(r["id"],))]
                result.append(x)
            return {"chapters":result}
    def draft(self,draft_id):
        self.initialize()
        with self.connection() as c:
            r=c.execute("SELECT id,title,body,chapter_number,revision,status,saved_at FROM drafts WHERE id=?",(draft_id,)).fetchone(); return dict(r) if r else None
    def patch_draft(self,draft_id,payload,key):
        self.initialize()
        with self.connection() as c:
            def build():
                d=c.execute("SELECT * FROM drafts WHERE id=?",(draft_id,)).fetchone()
                if not d: raise DomainError("draft_not_found",404)
                if len(payload["body"].encode())>120000: raise DomainError("draft_too_large",413)
                if payload["base_revision"]!=d["revision"]: raise DomainError("revision_conflict",409,details={"current_revision":d["revision"]})
                edit=payload.get("edit_context"); new=d["revision"]+1
                if edit:
                    run=c.execute("SELECT * FROM runs WHERE id=?",(edit["source_run_id"],)).fetchone(); issue=c.execute("SELECT * FROM issues WHERE id=?",(edit["issue_id"],)).fetchone()
                    if not run or not issue or issue["run_id"]!=run["id"] or run["status"]!="completed" or run["source_revision"]!=d["revision"] or edit["source_revision"]!=d["revision"]: raise DomainError("draft_invalid",422)
                    edit=json.dumps(edit,sort_keys=True)
                checksum=digest(payload["body"]); title=payload.get("title") or d["title"]; t=now(); c.execute("UPDATE drafts SET title=?,body=?,revision=?,saved_at=?,parent_revision=?,edit_context=?,body_checksum=? WHERE id=?",(title,payload["body"],new,t,d["revision"],edit,checksum,draft_id)); c.execute("INSERT INTO draft_revisions VALUES (?,?,?,?,?,?,?,?)",(draft_id,new,title,payload["body"],checksum,d["revision"],edit,t)); out={"id":draft_id,"revision":new,"saved_at":t,"body_checksum":checksum,"status":"saved"}
                if edit:out.update({"parent_revision":d["revision"],"edit_context":json.loads(edit),"lineage_status":"pending_decision_validation"})
                return out
            return self._idem(c,"patch_draft",key,payload,build)
    def memory(self,version=None,entity=None,memory_type=None,chapter=None):
        self.initialize()
        with self.connection() as c:
            p=c.execute("SELECT current_memory_version FROM projects WHERE id=?",(PROJECT["id"],)).fetchone(); v=int(version or p[0]);
            if not c.execute("SELECT 1 FROM memory_versions WHERE project_id=? AND version=?",(PROJECT["id"],v)).fetchone():raise DomainError("memory_version_not_found",404)
            if c.execute("SELECT 1 FROM memory_records m LEFT JOIN source_spans s ON s.id=m.source_span_id WHERE m.project_id=? AND m.version=? AND s.id IS NULL LIMIT 1",(PROJECT["id"],v)).fetchone(): raise DomainError("source_unavailable",422)
            sql="SELECT m.*,s.chapter_id,s.id span_id,s.body excerpt FROM memory_records m JOIN source_spans s ON s.id=m.source_span_id WHERE m.project_id=? AND m.version=?"; args=[PROJECT["id"],v]
            if entity:sql+=" AND (m.subject LIKE ? OR m.value LIKE ?)";args += [f"%{entity}%",f"%{entity}%"]
            if memory_type:sql+=" AND m.memory_type=?";args.append(memory_type)
            if chapter:sql+=" AND s.chapter_id=?";args.append(chapter)
            rows=c.execute(sql,args).fetchall(); return {"memory_version":v,"records":[{"id":r["id"],"memory_type":r["memory_type"],"subject":r["subject"],"predicate":r["predicate"],"value":r["value"],"valid_from":r["valid_from"],"valid_to":r["valid_to"],"review_status":r["review_status"],"source":{"chapter_id":r["chapter_id"],"span_id":r["span_id"],"excerpt":r["excerpt"]}} for r in rows]}

    def create_run(self, payload: dict[str, Any], key: str, provider_label: str):
        self.initialize()
        with self.connection() as c:
            def build():
                draft=c.execute("SELECT revision FROM drafts WHERE id=?",(payload["draft_id"],)).fetchone()
                if not draft: raise DomainError("draft_not_found",404)
                if payload["draft_revision"] != draft["revision"]: raise DomainError("draft_revision_not_current",409,details={"current_revision":draft["revision"]})
                active=c.execute("SELECT id FROM runs WHERE draft_id=? AND source_revision=? AND status IN ('queued','running')",(payload["draft_id"],draft["revision"])).fetchone()
                if active: raise DomainError("run_already_active",409,False, {"run_id":active["id"]})
                rid=f"run-{uuid.uuid4()}"; t=now()
                c.execute("INSERT INTO runs(id,project_id,draft_id,source_revision,status,stage,provider_label,created_at) VALUES (?,?,?,?,?,?,?,?)",(rid,PROJECT["id"],payload["draft_id"],draft["revision"],"queued","queued",provider_label,t))
                c.execute("INSERT INTO run_stages VALUES (?,?,?)",(rid,"queued",t))
                return {"run_id":rid,"status":"queued","stage":"queued","source_revision":draft["revision"],"created_at":t}
            return self._idem(c,"create_run",key,payload,build)

    def run_input(self, run_id: str):
        self.initialize()
        with self.connection() as c:
            run=c.execute("SELECT * FROM runs WHERE id=?",(run_id,)).fetchone()
            if not run: raise DomainError("run_not_found",404)
            draft=c.execute("SELECT * FROM draft_revisions WHERE draft_id=? AND revision=?",(run["draft_id"],run["source_revision"])).fetchone()
            claims=[]
            import re
            for index,text in enumerate(x.strip() for x in re.split(r"(?<=[。！？])",draft["body"]) if x.strip()):
                cid=f"claim-{run_id}-{index+1}"; claims.append({"id":cid,"text":text}); c.execute("INSERT OR IGNORE INTO run_claims VALUES (?,?,?,?)",(cid,run_id,index+1,text))
            historical=[dict(x) for x in c.execute("SELECT s.id,s.chapter_id,s.body,s.label FROM source_spans s JOIN chapters ch ON ch.id=s.chapter_id WHERE ch.project_id=? ORDER BY ch.chapter_number",(PROJECT["id"],))]
            memory=[dict(x) for x in c.execute("SELECT id,source_span_id,memory_type,subject,predicate,value FROM memory_records WHERE project_id=? AND version=4",(PROJECT["id"],))]
            for claim in claims:
                compact="".join(re.findall(r"[\u4e00-\u9fff]",claim["text"])); terms={compact[i:i+2] for i in range(max(0,len(compact)-1))}; scored=[]
                for span in historical:
                    score=sum(1 for term in terms if term in span["body"])
                    for mem in memory:
                        if mem["source_span_id"]==span["id"] and any(term in (mem["subject"]+mem["value"]) for term in terms): score+=2
                    if score: scored.append((score,span))
                hits=[x[1] for x in sorted(scored,key=lambda x:(-x[0],x[1]["id"]))[:5]]
                c.execute("INSERT OR REPLACE INTO retrieval_traces VALUES (?,?,?,?,?)",(run_id,claim["id"],",".join(sorted(terms))[:200],json.dumps([x["id"] for x in hits]),"demo-retrieval-v1")); claim["allowed_evidence"] = hits
            return {"run":dict(run),"draft":{"id":draft["draft_id"],"revision":draft["revision"],"body":draft["body"]},"claims":claims,"memory":memory}

    def advance_run(self, run_id: str, stage: str):
        with self.connection() as c:
            if not c.execute("SELECT 1 FROM runs WHERE id=?",(run_id,)).fetchone(): raise DomainError("run_not_found",404)
            c.execute("UPDATE runs SET status='running',stage=? WHERE id=?",(stage,run_id)); c.execute("INSERT OR IGNORE INTO run_stages VALUES (?,?,?)",(run_id,stage,now()))

    def session_budget_exhausted(self, limit:int=40000):
        self.initialize()
        with self.connection() as c:
            used=c.execute("SELECT COALESCE(SUM(COALESCE(input_tokens,0)+COALESCE(output_tokens,0)),0) FROM runs").fetchone()[0]
            return used>=limit

    def finish_run(self, run_id: str, result: dict[str, Any]):
        with self.connection() as c:
            status=result["status"]; stage={"completed":"completed","failed":"failed","timed_out":"timed_out","budget_paused":"budget_paused","cancelled":"cancelled"}.get(status,"failed")
            c.execute("UPDATE runs SET status=?,stage=?,latency_ms=?,input_tokens=?,output_tokens=?,cost_cny=?,error_code=?,retryable=?,completed_at=? WHERE id=?",(status,stage,result.get("latency_ms"),result.get("input_tokens"),result.get("output_tokens"),result.get("cost_cny"),result.get("error_code"),int(bool(result.get("retryable"))),now(),run_id)); c.execute("INSERT OR IGNORE INTO run_stages VALUES (?,?,?)",(run_id,stage,now()))
            if status!="completed": return
            for raw in result.get("issues",[]):
                iid=f"issue-{uuid.uuid4()}"; c.execute("INSERT INTO issues(id,run_id,claim_span_id,status,category,severity,evidence_status,explanation,proposed_change_json) VALUES (?,?,?,?,?,?,?,?,?)",(iid,run_id,raw["claim_span_id"],raw["status"],raw["category"],raw["severity"],raw["evidence_status"],raw["explanation"],json.dumps(raw.get("proposed_memory_change"),ensure_ascii=False)))
                for ev in raw.get("evidence",[]): c.execute("INSERT INTO evidence VALUES (?,?,?,?,?,?,?,?)",(f"ev-{uuid.uuid4()}",iid,ev["chapter_id"],ev["span_id"],ev["excerpt"],ev["relation"],ev["sufficiency"],json.dumps(ev.get("related_memory_ids",[]))))

    def _lineage(self,c,run):
        current=c.execute("SELECT revision,parent_revision,edit_context FROM drafts WHERE id=?",(run["draft_id"],)).fetchone()
        if current["revision"]==run["source_revision"]: return "current_source_revision"
        if current["revision"]==run["source_revision"]+1 and current["parent_revision"]==run["source_revision"] and current["edit_context"]:
            try: ctx=json.loads(current["edit_context"])
            except json.JSONDecodeError: return "superseded_unlinked"
            if ctx.get("source_run_id")==run["id"] and ctx.get("source_revision")==run["source_revision"]: return "validated_direct_successor"
        return "superseded_unlinked"

    def run_view(self, run_id: str, includes: set[str]):
        self.initialize()
        with self.connection() as c:
            run=c.execute("SELECT * FROM runs WHERE id=?",(run_id,)).fetchone()
            if not run: raise DomainError("run_not_found",404)
            if "evidence" in includes and run["error_code"]=="evidence_unresolvable": raise DomainError("evidence_unresolvable",422)
            lineage=self._lineage(c,run); current=c.execute("SELECT revision FROM drafts WHERE id=?",(run["draft_id"],)).fetchone()[0]
            out={"run_id":run["id"],"status":run["status"],"stage":run["stage"],"source_revision":run["source_revision"],"current_revision":current,"is_stale":lineage!="current_source_revision","superseded":lineage!="current_source_revision","lineage_status":lineage,"retryable":bool(run["retryable"]),"error_code":run["error_code"],"created_at":run["created_at"],"completed_at":run["completed_at"]}
            if "metrics" in includes:
                out["usage"]={"latency_ms":run["latency_ms"],"input_tokens":run["input_tokens"],"output_tokens":run["output_tokens"],"cost_cny":run["cost_cny"],"cost_status":"available" if run["cost_cny"] is not None else "unavailable"}
                out["observable_stages"]=[x["stage"] for x in c.execute("SELECT stage FROM run_stages WHERE run_id=? ORDER BY created_at",(run_id,))]
            if "issues" in includes:
                rows=c.execute("SELECT * FROM issues WHERE run_id=?",(run_id,)).fetchall(); out["issues"]=[]
                for x in rows:
                    decision=c.execute("SELECT id,decision,note,source_revision,resulting_revision,lineage_status,created_at FROM decisions WHERE issue_id=? ORDER BY created_at DESC LIMIT 1",(x["id"],)).fetchone()
                    claim=c.execute("SELECT text FROM run_claims WHERE id=? AND run_id=?",(x["claim_span_id"],run_id)).fetchone()
                    item={"id":x["id"],"status":x["status"],"category":x["category"],"severity":x["severity"],"evidence_status":x["evidence_status"],"explanation":x["explanation"],"claim_span_id":x["claim_span_id"],"claim_text":claim["text"] if claim else None,"decision":dict(decision) if decision else None}
                    if "evidence" in includes: item["evidence"]=self._evidence(c,x["id"])
                    out["issues"].append(item)
            return out

    def _evidence(self,c,issue_id):
        result=[]
        for x in c.execute("SELECT * FROM evidence WHERE issue_id=?",(issue_id,)):
            span=c.execute("SELECT chapter_id,body FROM source_spans WHERE id=?",(x["span_id"],)).fetchone()
            if not span or span["chapter_id"]!=x["chapter_id"] or span["body"]!=x["excerpt"]: raise DomainError("evidence_unresolvable",422)
            related=[]
            for memory_id in json.loads(x["related_memory_ids"]):
                row=c.execute("SELECT id,memory_type,subject,predicate,value FROM memory_records WHERE id=?",(memory_id,)).fetchone()
                if not row: raise DomainError("evidence_unresolvable",422)
                related.append({"id":row["id"],"memory_type":row["memory_type"],"summary":f'{row["subject"]} · {row["predicate"]} · {row["value"]}'})
            result.append({"id":x["id"],"chapter_id":x["chapter_id"],"span_id":x["span_id"],"excerpt":x["excerpt"],"relation":x["relation"],"sufficiency":x["sufficiency"],"related_memory":related})
        return result

    def decide(self, issue_id: str, payload: dict[str, Any], key: str):
        self.initialize()
        with self.connection() as c:
            def build():
                issue=c.execute("SELECT * FROM issues WHERE id=?",(issue_id,)).fetchone()
                if not issue: raise DomainError("issue_not_found",404)
                run=c.execute("SELECT * FROM runs WHERE id=?",(issue["run_id"],)).fetchone()
                if payload["run_id"]!=run["id"] or payload["source_revision"]!=run["source_revision"]: raise DomainError("invalid_decision",400)
                lineage=self._lineage(c,run)
                cur=c.execute("SELECT revision FROM drafts WHERE id=?",(run["draft_id"],)).fetchone()["revision"]
                resulting=None
                if payload["decision"]=="accept_and_edit":
                    evidence=c.execute("SELECT 1 FROM evidence WHERE issue_id=?",(issue_id,)).fetchone()
                    if issue["status"]=="conflict" and not evidence: raise DomainError("evidence_required_for_accept",422)
                    if lineage!="validated_direct_successor" or payload.get("resulting_revision")!=cur: raise DomainError("invalid_resulting_revision",422)
                    resulting=cur
                elif lineage not in {"current_source_revision","validated_direct_successor"}: raise DomainError("lineage_invalid_requires_recheck",409)
                elif lineage=="validated_direct_successor":
                    if payload.get("resulting_revision")!=cur: raise DomainError("invalid_resulting_revision",422)
                    resulting=cur
                elif payload.get("resulting_revision") is not None: raise DomainError("invalid_resulting_revision",422)
                if c.execute("SELECT 1 FROM decisions WHERE issue_id=? AND source_revision=?",(issue_id,run["source_revision"])).fetchone(): raise DomainError("already_decided",409)
                did=f"decision-{uuid.uuid4()}"; created=now(); c.execute("INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?)",(did,issue_id,run["id"],payload["decision"],payload.get("note"),run["source_revision"],resulting,lineage,created))
                return {"issue_id":issue_id,"decision":{"id":did,"decision":payload["decision"],"note":payload.get("note"),"source_revision":run["source_revision"],"resulting_revision":resulting,"lineage_status":lineage,"created_at":created,"author":"demo_author"},"issue_status":"resolved"}
            return self._idem(c,"decision:"+issue_id,key,payload,build)

    def create_changeset(self,payload:dict[str,Any],key:str):
        self.initialize()
        with self.connection() as c:
            def build():
                if payload["project_id"]!=PROJECT["id"]: raise DomainError("project_not_found",404)
                run=c.execute("SELECT * FROM runs WHERE id=?",(payload["run_id"],)).fetchone()
                if not run: raise DomainError("run_not_found",404)
                if payload["source_run_revision"]!=run["source_revision"]: raise DomainError("revision_mismatch",422)
                lineage=self._lineage(c,run)
                if lineage not in {"current_source_revision","validated_direct_successor"}: raise DomainError("lineage_invalid_requires_recheck",409)
                rev=c.execute("SELECT revision FROM drafts WHERE id=?",(run["draft_id"],)).fetchone()[0]
                if payload["resolved_revision"]!=rev: raise DomainError("revision_mismatch",422)
                issues=c.execute("SELECT id FROM issues WHERE run_id=?",(run["id"],)).fetchall(); decs=c.execute("SELECT * FROM decisions WHERE run_id=?",(run["id"],)).fetchall()
                if not issues or len(decs)<len(issues): raise DomainError("unresolved_required_decisions",409)
                eligible=[]
                for d in decs:
                    issue=c.execute("SELECT * FROM issues WHERE id=?",(d["issue_id"],)).fetchone(); proposal=json.loads(issue["proposed_change_json"] or "null")
                    if d["decision"]=="keep_intentional" and proposal: eligible.append((d,issue,proposal))
                if not eligible: raise DomainError("no_reviewable_changes",422)
                current=c.execute("SELECT current_memory_version FROM projects WHERE id=?",(PROJECT["id"],)).fetchone()[0]; cs=f"changeset-{uuid.uuid4()}"; target=current+1; rev=c.execute("SELECT revision FROM drafts WHERE id=?",(run["draft_id"],)).fetchone()[0]
                c.execute("INSERT INTO change_sets VALUES (?,?,?,?,?,?,?,?,?,?,?)",(cs,PROJECT["id"],run["id"],run["source_revision"],rev,lineage,current,target,"draft",now(),None))
                response_items=[]
                for d,issue,after in eligible:
                    before=None
                    if after["operation"]=="replace":
                        prior=c.execute("SELECT id,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to FROM memory_records WHERE id=? AND project_id=? AND version=?",(after.get("affected_memory_id"),PROJECT["id"],current)).fetchone()
                        if not prior: raise DomainError("no_reviewable_changes",422)
                        before=dict(prior)
                    iid=f"csi-{uuid.uuid4()}"; source_ids=[issue["id"],issue["claim_span_id"]]; decision_ids=[d["id"]]
                    c.execute("INSERT INTO change_set_items(id,change_set_id,operation,before_json,after_json,source_ids,decision_ids,review_status) VALUES (?,?,?,?,?,?,?,?)",(iid,cs,after["operation"],json.dumps(before,ensure_ascii=False) if before else None,json.dumps(after,ensure_ascii=False),json.dumps(source_ids),json.dumps(decision_ids),"pending"))
                    response_items.append({"id":iid,"operation":after["operation"],"before":before,"after":after,"source_ids":source_ids,"decision_ids":decision_ids})
                return {"change_set":{"id":cs,"status":"draft","base_memory_version":current,"target_memory_version":target,"source_run_revision":run["source_revision"],"resolved_revision":rev,"lineage_status":lineage,"items":response_items}}
            return self._idem(c,"create_changeset",key,payload,build)

    def commit_changeset(self, cs_id:str,payload:dict[str,Any],key:str):
        self.initialize()
        with self.connection() as c:
            def build():
                cs=c.execute("SELECT * FROM change_sets WHERE id=?",(cs_id,)).fetchone()
                if not cs: raise DomainError("change_set_not_found",404)
                if cs["status"]!="draft": raise DomainError("already_committed",409)
                current=c.execute("SELECT current_memory_version FROM projects WHERE id=?",(PROJECT["id"],)).fetchone()[0]
                if current!=cs["base_version"]: raise DomainError("base_version_changed",409)
                items=c.execute("SELECT * FROM change_set_items WHERE change_set_id=?",(cs_id,)).fetchall(); selected=set(payload.get("accepted_item_ids",[])); rejected=set(payload.get("rejected_item_ids",[])); known={x["id"] for x in items}
                if not selected and not rejected: raise DomainError("no_item_decisions",422)
                if selected&rejected or selected|rejected!=known: raise DomainError("invalid_item_selection",422)
                t=now(); audit_id=f"audit-{uuid.uuid4()}"
                if not selected:
                    c.execute("UPDATE change_sets SET status='rejected',committed_at=? WHERE id=?",(t,cs_id)); c.execute("UPDATE change_set_items SET review_status='rejected' WHERE change_set_id=?",(cs_id,))
                    c.execute("INSERT INTO commit_audits VALUES (?,?,?,?,?,?,?)",(audit_id,cs_id,"rejected",json.dumps([]),json.dumps(sorted(rejected)),payload.get("note"),t))
                    return {"change_set_id":cs_id,"status":"rejected","memory_version":{"previous":current,"current":current},"committed_item_ids":[],"rejected_item_ids":sorted(rejected),"audit_id":audit_id}
                c.execute("INSERT INTO memory_versions VALUES (?,?,?,?,?)",(PROJECT["id"],cs["target_version"],"current",t,current))
                c.execute("INSERT INTO memory_records(id,project_id,version,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to,source_claim_id) SELECT id||'-v'||?,project_id,?,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to,source_claim_id FROM memory_records WHERE project_id=? AND version=?",(cs["target_version"],cs["target_version"],PROJECT["id"],current))
                for x in items:
                    if x["id"] in selected:
                        after=json.loads(x["after_json"]); source_ids=json.loads(x["source_ids"]); issue_id=source_ids[0]; claim_id=source_ids[1]
                        evidence=c.execute("SELECT span_id FROM evidence WHERE issue_id=? ORDER BY id LIMIT 1",(issue_id,)).fetchone()
                        if after["operation"]=="replace":
                            target_id=after["affected_memory_id"]+f'-v{cs["target_version"]}'
                            prior=c.execute("SELECT source_span_id FROM memory_records WHERE id=? AND version=?",(target_id,cs["target_version"])).fetchone()
                            if not prior: raise DomainError("commit_failed",503,True)
                            source_span_id=evidence["span_id"] if evidence else prior["source_span_id"]
                            c.execute("UPDATE memory_records SET memory_type=?,subject=?,predicate=?,value=?,source_span_id=?,source_claim_id=?,review_status='author_confirmed' WHERE id=? AND version=?",(after["memory_type"],after["subject"],after["predicate"],after["value"],source_span_id,claim_id,target_id,cs["target_version"]))
                        else:
                            if not evidence: raise DomainError("commit_failed",503,True)
                            c.execute("INSERT INTO memory_records(id,project_id,version,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to,source_claim_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",(f"mem-{uuid.uuid4()}",PROJECT["id"],cs["target_version"],after["memory_type"],after["subject"],after["predicate"],after["value"],evidence["span_id"],"author_confirmed",None,None,claim_id))
                c.execute("UPDATE memory_versions SET status='superseded' WHERE project_id=? AND version=?",(PROJECT["id"],current)); c.execute("UPDATE projects SET current_memory_version=? WHERE id=?",(cs["target_version"],PROJECT["id"]))
                c.execute("UPDATE change_sets SET status='committed',committed_at=? WHERE id=?",(t,cs_id)); c.execute("UPDATE change_set_items SET review_status='accepted' WHERE id IN (%s)" % ','.join('?'*len(selected)),tuple(selected))
                if rejected: c.execute("UPDATE change_set_items SET review_status='rejected' WHERE id IN (%s)" % ','.join('?'*len(rejected)),tuple(rejected))
                c.execute("INSERT INTO commit_audits VALUES (?,?,?,?,?,?,?)",(audit_id,cs_id,"committed",json.dumps(sorted(selected)),json.dumps(sorted(rejected)),payload.get("note"),t))
                return {"change_set_id":cs_id,"status":"committed","memory_version":{"previous":current,"current":cs["target_version"]},"committed_item_ids":sorted(selected),"rejected_item_ids":sorted(rejected),"audit_id":audit_id}
            return self._idem(c,"commit_changeset:"+cs_id,key,payload,build)

    def reset(self, payload:dict[str,Any],key:str):
        self.initialize()
        with self.connection() as c:
            fp=digest(payload); old=c.execute("SELECT * FROM reset_audit WHERE idempotency_key=?",(key,)).fetchone()
            if old:
                if old["request_fingerprint"]!=fp: raise DomainError("idempotency_conflict",409)
                return json.loads(old["response_json"])
            for table in ["commit_audits","retrieval_traces","run_claims","evidence","decisions","issues","run_stages","runs","change_set_items","change_sets","write_idempotency","draft_revisions","drafts","memory_records","memory_versions","source_spans","chapters","projects","seed_metadata"]: c.execute(f"DELETE FROM {table}")
            self._seed(c); rid=f"reset-{uuid.uuid4()}"; completed=now(); out={"reset_id":rid,"project_id":PROJECT["id"],"current_memory_version":4,"draft_revision":1,"status":"completed","data_origin":"demo-specific"}; c.execute("INSERT INTO reset_audit VALUES (?,?,?,?,?,?)",(rid,key,fp,payload["reason"],completed,json.dumps(out))); return out

    def counts(self):
        self.initialize()
        with self.connection() as c:
            return {x:c.execute(f"SELECT COUNT(*) FROM {x}").fetchone()[0] for x in ["chapters","source_spans","memory_records","runs","issues","decisions","change_sets"]}
