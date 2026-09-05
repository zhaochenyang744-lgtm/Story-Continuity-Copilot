import hashlib
import json
import pathlib
import tempfile
import unittest

from app.provider import ProviderResult
from tools.run_stage11l_real_100k import RunFailure, formal_run, redacted_base, response_data
from tools.validate_stage11l_real_100k import LEGACY_V1_RESULT_SHA256, LEGACY_V2_RESULT_SHA256, LEGACY_V3_RESULT_SHA256, LEGACY_V4_RESULT_SHA256, LEGACY_V5_RESULT_SHA256, validate_result


class FakeResponse:
    def __init__(self,status_code,payload):
        self.status_code=status_code
        self.payload=payload

    def json(self):
        return self.payload


class Stage11LFailureObservabilityTests(unittest.TestCase):
    def base(self):
        data=redacted_base("container","01b7cb6ca01c86a56e69bd5c897efc0f377b32b8da4b4274c326a9135b437af1",100000,286451)
        data.update({"status":"gate_failed","provider_http_calls":21,"provider_successful_responses":21,"provider_model_label":"deepseek-v4-pro","model_output_auto_canon":False})
        return data

    def test_runner_keeps_only_allowlisted_failure_details(self):
        response=FakeResponse(503,{"error":{"code":"evidence_unresolvable","message":"do not persist","details":{"failure_phase":"post_response_validation","failed_batch_ordinal":22,"total_batches":27,"input_tokens":321,"output_tokens":45,"latency_ms":678,"cost_available":False,"source_text":"SECRET","raw_provider_body":"SECRET"}}})
        with self.assertRaises(RunFailure) as raised:
            response_data(response,201,"initialization_failed")
        fields=raised.exception.result_fields()
        self.assertEqual(fields,{"stop_reason":"evidence_unresolvable","failure_http_status":503,"failure_phase":"post_response_validation","failed_batch_ordinal":22,"total_batches":27,"input_tokens":321,"output_tokens":45,"latency_ms":678,"cost_available":False})
        self.assertNotIn("SECRET",json.dumps(fields))

    def test_runner_falls_back_for_unknown_error_code_and_discards_untrusted_details(self):
        response=FakeResponse(503,{"error":{"code":"provider said secret","details":{"failure_phase":"invented","failed_batch_ordinal":"22","total_batches":-1,"prompt":"SECRET"}}})
        with self.assertRaises(RunFailure) as raised:
            response_data(response,201,"initialization_failed")
        self.assertEqual(raised.exception.result_fields(),{"stop_reason":"initialization_failed","failure_http_status":503})

    def test_validator_accepts_exact_legacy_v1_but_rejects_new_vague_failure(self):
        legacy=pathlib.Path(__file__).resolve().parents[2] / "artifacts" / "test-records" / "stage11" / "real-novel-100k-11l-v1" / "results.json"
        raw=legacy.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),LEGACY_V1_RESULT_SHA256)
        self.assertTrue(validate_result(json.loads(raw.decode("utf-8")),LEGACY_V1_RESULT_SHA256))
        legacy_v2=legacy.parents[1] / "real-novel-100k-11l-v2" / "results.json"
        raw_v2=legacy_v2.read_bytes()
        self.assertEqual(hashlib.sha256(raw_v2).hexdigest(),LEGACY_V2_RESULT_SHA256)
        self.assertTrue(validate_result(json.loads(raw_v2.decode("utf-8")),LEGACY_V2_RESULT_SHA256))
        legacy_v3=legacy.parents[1] / "real-novel-100k-11l-v3" / "results.json"
        raw_v3=legacy_v3.read_bytes()
        self.assertEqual(hashlib.sha256(raw_v3).hexdigest(),LEGACY_V3_RESULT_SHA256)
        self.assertTrue(validate_result(json.loads(raw_v3.decode("utf-8")),LEGACY_V3_RESULT_SHA256))
        legacy_v4=legacy.parents[1] / "real-novel-100k-11l-v4" / "results.json"
        raw_v4=legacy_v4.read_bytes()
        self.assertEqual(hashlib.sha256(raw_v4).hexdigest(),LEGACY_V4_RESULT_SHA256)
        self.assertTrue(validate_result(json.loads(raw_v4.decode("utf-8")),LEGACY_V4_RESULT_SHA256))
        legacy_v5=legacy.parents[1] / "real-novel-100k-11l-v5" / "results.json"
        raw_v5=legacy_v5.read_bytes()
        self.assertEqual(hashlib.sha256(raw_v5).hexdigest(),LEGACY_V5_RESULT_SHA256)
        self.assertTrue(validate_result(json.loads(raw_v5.decode("utf-8")),LEGACY_V5_RESULT_SHA256))
        vague=self.base(); vague["stop_reason"]="initialization_failed"
        self.assertFalse(validate_result(vague,"different-result-hash"))

    def test_validator_accepts_specific_v2_failure_and_rejects_invalid_batch_metadata(self):
        result=self.base()
        result.update({"stop_reason":"schema_invalid","failure_http_status":503,"failure_phase":"post_response_validation","failed_batch_ordinal":22,"total_batches":27,"input_tokens":321,"output_tokens":45,"latency_ms":678,"cost_available":False})
        self.assertTrue(validate_result(result,"different-result-hash"))
        result["failed_batch_ordinal"]=28
        self.assertFalse(validate_result(result,"different-result-hash"))
        for vague in (None,"","unclassified_formal_failure"):
            result=self.base(); result["stop_reason"]=vague
            self.assertFalse(validate_result(result,"different-result-hash"))
        result=self.base(); result.update({"stop_reason":"schema_invalid","failure_phase":"post_response_validation","failed_batch_ordinal":1,"total_batches":1,"source_text":"SECRET"})
        self.assertFalse(validate_result(result,"different-result-hash"))

    def test_validator_requires_v6_success_metrics_retrieval_and_bounded_repair(self):
        result=self.base()
        counts={table:1 for table in ("v2_memory_initializations","v2_memory_candidates","v2_memory_candidate_decisions","v2_runs","v2_issues","v2_evidence","v2_memory_delta_batches","v2_memory_delta_candidates","v2_memory_delta_decisions","v2_source_coverage_audits","v2_memory_records")}
        retrieval={"continuity":"bounded-lexical-v4-longform","memory_delta":"bounded-lexical-v4-longform"}
        result.update({"status":"completed_pending_independent_gate","stop_reason":None,"source_revisions":[1,2,3],"memory_versions":[1,2,3],"pending_canon_count":0,"lineage_unresolved_count":0,"business_table_counts":counts,"controlled_regression_chapters":2,"initialization_core_decisions":1,"incremental_rounds":[{"memory_version":2,"coverage_status":"covered_with_memory_change","run_types":["continuity","memory_delta"],"core_decisions":1,"retrieval_method_versions":retrieval,"retrieval_trace_count":2},{"memory_version":3,"coverage_status":"covered_with_memory_change","run_types":["continuity","memory_delta"],"core_decisions":1,"retrieval_method_versions":retrieval,"retrieval_trace_count":2}],"initialization_metrics":{"total_batches":27,"schema_repair_attempts":2,"validated_batches":27,"staged_candidate_count":90,"normalization_count":1,"normalization_kinds":{"trimmed_string":1},"repair_events":[{"batch_ordinal":18,"attempt":1,"batch_attempt":1,"reason_code":"required_field_blank","result":"failed","final_reason_code":"required_field_blank","field":"value","candidate_ordinal":2},{"batch_ordinal":18,"attempt":2,"batch_attempt":2,"reason_code":"required_field_blank","result":"succeeded","field":"value","candidate_ordinal":2}],"input_tokens":100,"output_tokens":20,"latency_ms":30,"cost_available":False},"initialization_provenance":{"provider_label":"deepseek","model_label":"deepseek-v4-pro","provider_api_format":"chat-completions-json-object","prompt_version":"memory-initialization-v8-pro-two-repair","schema_version":"memory-candidate-v1","chunking_method_version":"source-chunk-v4-5800"}})
        self.assertTrue(validate_result(result,"v4-result-hash"))
        result["initialization_metrics"]["schema_repair_attempts"]=6
        self.assertFalse(validate_result(result,"v4-result-hash"))

    def test_v6_formal_runner_completes_two_bounded_retrieval_rounds_with_injected_pro_provider(self):
        class Provider:
            available=True; label="deepseek"; model_label="deepseek-v4-pro"; api_format_label="chat-completions-json-object"; max_retries=0; request_cap=36
            def __init__(self):self.request_attempts=0; self.successful_responses=0
            def evaluate(self,request):
                self.request_attempts+=1; self.successful_responses+=1
                if request.get("task")=="memory_initialization":
                    source=request["sources"][0]; payload={"candidates":[{"memory_type":"static_canon","subject":"基准人物","predicate":"status","value":"已建立基准","chapter_id":source["chapter_id"],"source_span_id":source["id"]}]}
                elif request.get("task")=="memory_delta":
                    source=request["sources"][0]; payload={"candidates":[{"change_kind":"new_fact","affected_memory_id":None,"memory_type":"dynamic_state","subject":f"测试记录员{request['source_revision']}","predicate":"status","value":f"已完成第{request['source_revision']}版受控书签动作","invalidation_reason":None,"chapter_id":source["chapter_id"],"source_span_id":source["id"]}]}
                else:payload={"issues":[]}
                return ProviderResult(payload,input_tokens=10,output_tokens=5,latency_ms=1)
        root=pathlib.Path(tempfile.mkdtemp(prefix="scc-11l-v6-runner-"))/"isolated"
        result=formal_run("# 第一章\n基准人物已建立基准。",root,Provider())
        self.assertEqual((result["status"],result["source_revisions"],result["memory_versions"],result["pending_canon_count"]),("completed_pending_independent_gate",[1,2,3],[1,2,3],0))
        self.assertTrue(all(row["retrieval_method_versions"]=={"continuity":"bounded-lexical-v4-longform","memory_delta":"bounded-lexical-v4-longform"} and row["retrieval_trace_count"]>=1 for row in result["incremental_rounds"]))

    def test_v6_formal_runner_rejects_non_pro_before_provider_call(self):
        class Provider:
            available=True; label="deepseek"; model_label="deepseek-v4-flash"; request_attempts=0; successful_responses=0; max_retries=0; request_cap=36
        root=pathlib.Path(tempfile.mkdtemp(prefix="scc-11l-v6-model-gate-"))/"isolated"
        with self.assertRaises(RunFailure) as raised:
            formal_run("# 第一章\n基准。",root,Provider())
        self.assertEqual((raised.exception.code,Provider.request_attempts),("provider_model_not_pro",0))


if __name__ == "__main__":
    unittest.main()
