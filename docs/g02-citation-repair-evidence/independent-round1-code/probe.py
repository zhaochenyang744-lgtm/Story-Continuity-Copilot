"""Controller G02 probes: pure validate calls over synthetic dictionaries, no Provider or DB."""
import copy
import hashlib
import json
import pathlib
import sys

sys.dont_write_bytecode=True
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/"backend"))
from app.engine import WritingAnalysisEngine
from app import brief_citations

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
sources=[ROOT/"backend/app/brief_citations.py",ROOT/"backend/app/engine.py",ROOT/"backend/app/v2_database.py"]
before={str(p.relative_to(ROOT)):sha(p) for p in sources}
freeze=json.loads((ROOT/"evaluation/current_flash_v4/frozen-inputs.json").read_text(encoding="utf-8"))
engine=WritingAnalysisEngine(None)

def data(claims=(),spans=(),memory=(),planned=None):
    claims=[{"id":f"c{i+1}","ordinal":i+1,"text":text} for i,text in enumerate(claims)]
    return {"task":"context_brief","bindings":{"project_id":"synthetic-only","draft_revision":1,"memory_version":1},
            "layers":{"written":{"draft":{"id":"d","revision":1,"excerpt":"".join(c["text"] for c in claims)},"draft_claims":claims,
                                  "source_spans":[{"id":f"s{i+1}","chapter_id":f"ch{i+1}","chapter_number":i+1,"label":"独立合成原文","body":text} for i,text in enumerate(spans)]},
                      "confirmed":{"memory_records":list(memory)},"planned":planned or {"story_plans":[],"character_plans":[],"world_plans":[]}},
            "retrieval":{"truncated":{},"draft_claim_scope":{"available":len(claims),"selected":[{"id":c["id"],"truncated":False} for c in claims]}}}
def ref(kind,sid): return {"source_type":kind,"source_id":sid}
def item(text,refs,section="recent_source"): return {"section":section,"text":text,"sources":refs}
def validate(d,items):
    payload={"summary":"不应使用的模型自由摘要，虚构月球坠落。","summary_sources":items[0]["sources"][:3],"items":items}
    return engine.validate(payload,copy.deepcopy(d))
rows=[]
def record(name,input_data,model_items,predicate,expected):
    try:
        result=validate(input_data,model_items)
        actual=predicate(result)
        rows.append({"name":name,"pass":actual==expected,"expected":expected,"actual":actual,"model_items":model_items,"result":result})
    except Exception as error:
        rows.append({"name":name,"pass":False,"error_type":type(error).__name__,"error":str(error)})

texts=["岑岚走进东门。","赤铜钥匙已经交给乔霁。","温岚此时不知道暗号。"]
d=data(claims=texts)
record("normal_three_fact_usefulness",d,[item(t,[ref("draft_claim",f"c{i+1}")]) for i,t in enumerate(texts)],
       lambda r:all(any(t in v["text"] for v in r["items"]) for t in texts) and r["draft_coverage"]["status"]=="covered",True)
record("cyclic_citation_paraphrases",d,[item(t,[ref("draft_claim",f"c{(i+1)%3+1}")]) for i,t in enumerate(["岑岚从东门进入。","乔霁接过赤铜钥匙。","温岚还未掌握暗号。")],
       lambda r:all(any(t in v["text"] and any(s["source_id"]==f"c{i+1}" for s in v["sources"]) for v in r["items"]) for i,t in enumerate(texts)),True)

for label,assertion,actual in [
    ("negative","顾遥知道密码。","顾遥没有知道密码，也从未被告知。"),
    ("time","顾遥18点已知道密码。","顾遥18点尚不知道密码，直到19点才获知。"),
    ("quotation","顾遥知道密码。","顾遥说：‘我知道密码。’旁白立即指出这是谎言，她实际不知道。"),
    ("relationship","顾遥从乔霁手里拿到赤钥。","顾遥把赤钥交给乔霁，随后独自离开。"),
]:
    record(label,data(spans=[actual]),[item(assertion,[ref("source_span","s1")])],
           lambda r,a=actual:all(a in v["text"] and "所选原文" in v["text"] for v in r["items"]),True)

memory={"id":"m1","memory_type":"character_knowledge","subject":"温岚","predicate":"does_not_know","value":"廊桥钥匙的含义"}
d=data(spans=["温岚看得懂潮表上的坐标，却不知道廊桥钥匙的含义。"],memory=[memory])
record("multifact_own_source_supplement",d,[item("温岚看得懂潮表上的坐标，但不知道廊桥钥匙的含义。",[ref("memory_record","m1")])],
       lambda r:any("看得懂潮表上的坐标" in v["text"] and any(s["source_id"]=="s1" for s in v["sources"]) for v in r["items"]),True)
tail="最后把银钥匙交给陈澈并得知弟弟还活着。"
long_claim="林默沿着長廊向前走，"*26+tail
record("under_540_tail_kept",data(claims=[long_claim]),[item("林默走过长廊，"+tail,[ref("draft_claim","c1")])],
       lambda r:any(tail in v["text"] and tail in v["sources"][0]["excerpt"] for v in r["items"]),True)

# One absent assertion clause causes the fallback record, but should not count twice.
holder={"id":"m1","memory_type":"dynamic_state","subject":"星钥","predicate":"holder","value":"乔霁"}
record("single_unmatched_clause_count",data(memory=[holder]),[item("外星访客夺走紫色皇冠。",[ref("memory_record","m1")])],
       lambda r:r["citation_transform"]["omitted_unmatched_clause_count"],1)

# Bound source lengths accepted by the existing API: one rendered multi-source item can split into four.
span_facts=["北塔挂着红灯。","南塔挂着蓝灯。","东塔挂着金灯。","西塔挂着白灯。"]
spans=[fact+"这里记录塔楼的石阶与长廊。"*35 for fact in span_facts]
d=data(claims=texts,spans=spans,memory=[holder])
all_refs=[ref("source_span",f"s{i+1}") for i in range(4)]
model_items=[item("".join(span_facts),all_refs) for _ in range(3)]
model_items += [item(t,[ref("draft_claim",f"c{i+1}")]) for i,t in enumerate(texts)]
model_items += [item("星钥由乔霁保管。",[ref("memory_record","m1")],"character_state") for _ in range(6)]
record("split_expansion_preserves_later_valid_draft_facts",d,model_items,
       lambda r:all(any(t in v["text"] for v in r["items"]) for t in texts),True)

# All source text is bound input, but later author fields do not appear in the cleaned excerpt.
planned={"story_plans":[{"id":"p1","title":"钟楼计划","summary":"计划清晨关闭城门。","goal":"计划傍晚重新开门。"}],"character_plans":[],"world_plans":[]}
record("author_field_own_excerpt_coverage",data(planned=planned),[item("计划清晨关闭城门，傍晚重新开门。",[ref("author_context","p1")],"related_plan")],
       lambda r:all("计划傍晚重新开门" not in v["text"] or any("计划傍晚重新开门" in s["excerpt"] for s in v["sources"]) for v in r["items"]),True)

after={str(p.relative_to(ROOT)):sha(p) for p in sources}
out={"scope":"Pure validator and source-renderer tests. No DB, network, credential, Provider, product or original evidence writes.",
     "source_hashes_before":before,"source_hashes_after":after,"source_unchanged":before==after,
     "matches_v4_freeze":{k:v==freeze["source_hashes"].get(k) for k,v in before.items()},"cases":rows,
     "passed":sum(r["pass"] for r in rows),"total":len(rows)}
with (HERE/"results.json").open("x",encoding="utf-8") as f:json.dump(out,f,ensure_ascii=False,indent=2)
print(json.dumps({"passed":out["passed"],"total":out["total"],"failures":[r["name"] for r in rows if not r["pass"]],"source_unchanged":before==after},ensure_ascii=False))
