"""Independent post-V4 boundary controls, using the actual DB-preparation AST but no DB."""
from pathlib import Path
old=Path(__file__).parent.parent/"independent-round1-code/probe.py"
exec(compile(old.read_text(encoding="utf-8").split("rows=[]")[0],str(old),"exec"))
import ast
import re

tests=[]
def check(name,actual,expected,detail=None):
    tests.append({"name":name,"actual":actual,"expected":expected,"pass":actual==expected,"detail":detail})

holder={"id":"m1","memory_type":"dynamic_state","subject":"星钥","predicate":"holder","value":"乔霁"}
for name,text,want in [
    ("one_unmatched_clause","外星访客夺走紫色皇冠。",1),
    ("two_unmatched_clauses","外星访客夺走紫色皇冠。南海巨兽正在吞噬星球。",2),
    ("matched_clause","星钥由乔霁保管。",0),
]:
    result=validate(data(memory=[holder]),[item(text,[ref("memory_record","m1")])])
    check(name,result["citation_transform"]["omitted_unmatched_clause_count"],want,result)

texts=["岑岚走进东门。","赤铜钥匙已经交给乔霁。","温岚此时不知道暗号。"]
d=data(claims=texts,memory=[holder])
model=[item(texts[0],[ref("draft_claim","c1")])]*3
result=validate(d,model)
check("duplicate_dedup_keeps_all_selected_draft",{c:any(t in v["text"] for v in result["items"]) for c,t in zip(("c1","c2","c3"),texts)},{"c1":True,"c2":True,"c3":True},result)
check("duplicate_omission_count",result["citation_transform"]["duplicate_omitted_item_count"],2)
check("missing_model_draft_fallback_ids",result["citation_transform"]["fallback_draft_claim_ids"],["c2","c3"])
check("duplicate_output_no_repeated_cards",len(result["items"]),3)

# Multiple short valid facts can share one card; reserving by claims must not duplicate that card.
joint=validate(data(claims=texts),[item("".join(texts),[ref("draft_claim",f"c{i+1}") for i in range(3)])])
check("multisource_short_card_preserves_all_facts",all(t in " ".join(v["text"] for v in joint["items"]) for t in texts),True,joint)
check("multisource_short_card_coverage",joint["draft_coverage"]["status"],"covered")
check("multisource_short_card_not_duplicated",len(joint["items"]),1)

# Actual current mapper emits one substantive Author Context body field and blank goal.
planned={"story_plans":[{"id":"p1","title":"钟楼计划","summary":"计划清晨关闭城门。","goal":""}],"character_plans":[],"world_plans":[]}
plan=validate(data(planned=planned),[item("清晨关门的计划。",[ref("author_context","p1")],"related_plan")])
check("current_plan_shape_keeps_plan_layer",plan["items"][0]["section"],"related_plan",plan)
check("current_plan_body_has_own_excerpt",all(v["sources"][0]["excerpt"] in v["text"] for v in plan["items"]),True)

# Execute the exact source prep selection/claim loop from V2Database; no product DB import/creation.
tree=ast.parse((ROOT/"backend/app/v2_database.py").read_text(encoding="utf-8"))
assignment=next(n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="draft_parts" for t in n.targets))
claim_loop=next(n for n in ast.walk(tree) if isinstance(n,ast.For) and isinstance(n.iter,ast.Call) and isinstance(n.iter.func,ast.Name) and n.iter.func.id=="enumerate" and n.iter.args and isinstance(n.iter.args[0],ast.Name) and n.iter.args[0].id=="draft_parts")
compiled=compile(ast.Module(body=[assignment,claim_loop],type_ignores=[]),str(ROOT/"backend/app/v2_database.py"),"exec")
def construct(body,task="context_brief"):
    scope={"analysis_type":task,"draft_text":body,"draft":{"id":"independent-draft","revision":2},"all_claims":[],"claim_scopes":{},"cursor":0,"re":re,"split_draft_claims":brief_citations.split_draft_claims}
    exec(compiled,scope)
    return scope["all_claims"],scope["claim_scopes"]

quote_cases=[
    ("curly_dialogue",'温岚说：“我不知道密码。”顾遥回答：“我也不知道。”',['温岚说：“我不知道密码。”','顾遥回答：“我也不知道。”']),
    ("nested_curly",'温岚说：“顾遥曾喊‘不要开门！’，所以我没有开门。”她随后离开。',['温岚说：“顾遥曾喊‘不要开门！’，所以我没有开门。”','她随后离开。']),
    ("nested_corner",'温岚说：「顾遥说过『密码未知。』我也不知道。」门外安静。',['温岚说：「顾遥说过『密码未知。』我也不知道。」','门外安静。']),
    ("terminal_outside_quote",'温岚说：“我不知道密码”。顾遥离开。',['温岚说：“我不知道密码”。','顾遥离开。']),
    ("multiple_sentences_in_one_quote",'温岚说：“我不知道密码。也不认识信使。”顾遥点头。',['温岚说：“我不知道密码。也不认识信使。”','顾遥点头。']),
]
for label,body,expected in quote_cases:
    claims,scopes=construct(body)
    check(label,[c["text"] for c in claims],expected,{"claims":claims,"scopes":scopes})
    check(label+"_source_offsets",all(body[scopes[c["id"]]["source_start"]:scopes[c["id"]]["supplied_end"]]==c["text"] for c in claims),True)
    qdata=data(claims=[c["text"] for c in claims])
    rendered=validate(qdata,[item("错误模型只说温岚已经知道密码。",[ref("draft_claim","c1")])])
    check(label+"_all_complete_quotes_rendered",all(any(t in v["text"] for v in rendered["items"]) for t in expected),True,rendered)

long="林默走过石桥，"*40+"最终没有交出星钥。"
new_claims,new_scopes=construct(long)
old_claims,old_scopes=construct(long,"story_qa")
check("only_brief_uses_540_limit",[len(new_claims[0]["text"]),len(old_claims[0]["text"])],[len(long),240])

# These input classes are recorded as limitations, not expanded into this repair's acceptance contract.
limits=[]
for label,body in [
    ("ascii_quote",'Wen said: "I do not know the code." Gu replied: "Neither do I."'),
    ("postposed_speaker",'“我不知道密码。”温岚低声回答。'),
    ("quote_embedded_in_larger_sentence",'温岚对“你知道密码吗？”这一问保持沉默。'),
]:
    claims,scopes=construct(body)
    limits.append({"name":label,"input":body,"claims":claims,"note":"Bounded splitter observation; no general multilingual speech parser claim."})

after={str(p.relative_to(ROOT)):sha(p) for p in sources}
out={"scope":"Pure validator plus extracted actual V2Database claim-construction statements; no Provider or SQL", "source_hashes_before":before,"source_hashes_after":after,"source_unchanged":before==after,
     "checks":tests,"passed":sum(t["pass"] for t in tests),"total":len(tests),"recorded_splitter_limits":limits}
with (HERE/"boundary-results.json").open("x",encoding="utf-8") as f:json.dump(out,f,ensure_ascii=False,indent=2)
print(json.dumps({"passed":out["passed"],"total":out["total"],"failed":[t["name"] for t in tests if not t["pass"]],"source_unchanged":before==after},ensure_ascii=False))
