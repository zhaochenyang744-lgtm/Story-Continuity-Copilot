"""Local-only failure classification and saved snapshot audit; no runner import."""
import ast
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
EVAL = HERE.parent
RUN = EVAL / "runs/flash-v1-20260926-01"
tree = ast.parse((EVAL / "run.py").read_text(encoding="utf-8"))
# Execute exactly the runner's counter condition under synthetic terminal states.
condition = next(n for n in ast.walk(tree) if isinstance(n, ast.If) and n.lineno == 424)
code = compile(ast.Module(body=[condition], type_ignores=[]), str(EVAL / "run.py"), "exec")
probes = []
for label, states in [
    ("two_evidence_failures", [{"status":"failed","error_code":"evidence_unresolvable"}]*2),
    ("two_provider_errors", [{"status":"failed","error_code":"provider_error"}]*2),
    ("business_failure_then_completed", [{"status":"failed","error_code":"evidence_unresolvable"},{"status":"completed"}]),
]:
    scope = {"consecutive_service_errors":0}
    counts = []
    for terminal in states:
        scope.update(terminal=terminal,status=terminal.get("terminal_status",terminal.get("status")))
        exec(code,scope)
        counts.append(scope["consecutive_service_errors"])
    probes.append({"case":label,"counts":counts,"stops_matrix":counts[-1] >= 2})

def citation_ids(value):
    if isinstance(value,dict):
        if value.get("source_type") == "memory_record" and value.get("source_id"):
            yield value["source_id"], value.get("excerpt")
        for child in value.values():
            yield from citation_ids(child)
    elif isinstance(value,list):
        for child in value:
            yield from citation_ids(child)

rows = []
for path in sorted((RUN/"cases").glob("*.json")):
    record = json.loads(path.read_text(encoding="utf-8"))
    if record["family"] not in {"g02","g03"}:
        continue
    first = record["model_outputs"][0]
    model_ids = {sid for sid,_ in citation_ids(first["business_json"])}
    resolved_product_ids = {sid for sid,excerpt in citation_ids(record["product"].get("analysis")) if excerpt}
    rows.append({"case_id":record["case_id"],"product_status":record["product"]["status"],
                 "source_memory_version":record["product"].get("source_memory_version"),
                 "input_digest":record["product"].get("input_digest"),
                 "memory_catalog_saved":any(k in first["input_refs"] for k in ("confirmed","memory","memory_records","layers")),
                 "first_model_memory_citation_count":len(model_ids),
                 "first_model_memory_citations_not_in_saved_product_excerpts":sorted(model_ids-resolved_product_ids)})
out={"method":"AST-isolated current service-stop condition; first-model citation IDs checked against saved final product excerpts",
     "counter_probes":probes,"snapshot_limitations":rows,
     "scope":"No HTTP, credentials, DB, product modifications, or implementation evidence modifications"}
with (HERE/"accounting-stop-snapshot-results.json").open("x",encoding="utf-8") as f:
    json.dump(out,f,ensure_ascii=False,indent=2)
print(json.dumps(out,ensure_ascii=False))
