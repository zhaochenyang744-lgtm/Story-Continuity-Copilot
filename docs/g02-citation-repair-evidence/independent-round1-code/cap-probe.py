"""Distinct valid model items reproduce final capacity loss without duplicate model items."""
from pathlib import Path
base=Path(__file__).with_name("probe.py").read_text(encoding="utf-8").split("rows=[]")[0]
exec(compile(base,str(Path(__file__).with_name("probe.py")),"exec"))
texts=["岑岚走进东门。","赤铜钥匙已经交给乔霁。","温岚此时不知道暗号。"]
span_facts=["北塔挂着红灯。","南塔挂着蓝灯。","东塔挂着金灯。","西塔挂着白灯。"]
spans=[fact+"这里记录塔楼的石阶与长廊。"*35 for fact in span_facts]
objects=["青铜铃","封蜡印","星图筒","银羽扇","白瓷壶","旧铜锁","墨玉牌","红丝带"]
memory=[{"id":f"m{i+1}","memory_type":"dynamic_state","subject":obj,"predicate":"holder","value":"顾遥"} for i,obj in enumerate(objects)]
d=data(claims=texts,spans=spans,memory=memory)
model_items=[item("".join(span_facts),[ref("source_span",f"s{i+1}") for i in range(4)])]
model_items += [item(f"{obj}由顾遥保管。",[ref("memory_record",f"m{i+1}")],"character_state") for i,obj in enumerate(objects)]
model_items += [item(t,[ref("draft_claim",f"c{i+1}")]) for i,t in enumerate(texts)]
assert len(model_items)==12 and len({v["text"] for v in model_items})==12
result=validate(d,model_items)
preserved={f"c{i+1}":any(t in v["text"] for v in result["items"]) for i,t in enumerate(texts)}
out={"scope":"Pure validator, all 12 distinct valid model items, supplied spans each below 500 chars, eight selected Memory records, three complete draft claims",
     "inputs":d,"model_items":model_items,"result":result,"draft_facts_preserved":preserved,
     "failure":not all(preserved.values()),"span_lengths":[len(x) for x in spans],
     "source_hashes":{str(p.relative_to(ROOT)):sha(p) for p in sources}}
with (HERE/"cap-results.json").open("x",encoding="utf-8") as f:json.dump(out,f,ensure_ascii=False,indent=2)
print(json.dumps({"draft_facts_preserved":preserved,"output_item_count":len(result["items"]),"coverage":result["draft_coverage"],"transform":result["citation_transform"]},ensure_ascii=False))
