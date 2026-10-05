"""Normalize Windows path separators when comparing recorded hashes with the freeze manifest."""
import hashlib
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
recorded=json.loads((HERE/"results.json").read_text(encoding="utf-8"))
manifest_path=ROOT/"evaluation/current_contract_compare_v1/frozen-inputs.json"
manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
checks=[]
for native_path,before in recorded["source_hashes_before"].items():
    path=native_path.replace("\\","/")
    current=hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
    expected=manifest["source_hashes"].get(path)
    checks.append({"path":path,"test_before_hash":before,"current_hash":current,"frozen_hash":expected,"pass":before==current==expected})
out={"method":"Exact SHA256 using manifest-normalized forward-slash relative paths","checks":checks,"all_pass":all(c["pass"] for c in checks),
     "manifest_sha256":hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
     "prior_boolean_note":"The replay retained original probe code that used Windows backslash path keys to look up forward-slash manifest keys. Its matches_current_comparison_freeze flags are false due to key mismatch; this separate result corrects the comparison without overwriting the first output."}
with (HERE/"source-verification.json").open("x",encoding="utf-8") as f:json.dump(out,f,ensure_ascii=False,indent=2)
print(json.dumps(out,ensure_ascii=False))
