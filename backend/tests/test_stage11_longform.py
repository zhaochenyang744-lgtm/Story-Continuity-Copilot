import json
import pathlib, tempfile, unittest, uuid

from app.engine import ContinuityEngine, MemoryDeltaEngine, MemoryInitializationEngine
from app.memory_contract import CONTROLLED_PREDICATES, is_controlled_candidate
from app.provider import DeepSeekProvider, InputBudgetExceeded, ProviderFailure, ProviderInvalidJson, ProviderResult, ProviderTimeout, memory_initialization_prompt, request_prompt_and_budget
from app.v2_database import V2Database
from app.config import AppPaths


def source(index, chars=2600):
    return {"id": f"span-{index}", "chapter_id": f"chapter-{index}", "chapter_number": index,
            "chapter_title": f"Chapter {index}", "label": "import", "body": "甲" * chars}


class BatchProvider:
    available = True
    label = "stage11-batch-provider"
    model_label = "stage11-batch-model"

    def __init__(self, fail_at=None):
        self.calls = []
        self.fail_at = fail_at

    def evaluate(self, request):
        self.calls.append(request)
        if self.fail_at == len(self.calls):
            raise ProviderTimeout()
        if request.get("task") == "memory_initialization":
            return ProviderResult({"candidates": [{"memory_type": "static_canon", "subject": item["id"], "predicate": "fact", "value": "confirmed", "chapter_id": item["chapter_id"], "source_span_id": item["id"]} for item in request["sources"]]}, input_tokens=100, output_tokens=10, latency_ms=7, cost_cny=0.1)
        issues = []
        for claim in request["claims"]:
            evidence = claim["allowed_evidence"][0]
            issues.append({"claim_span_id": claim["id"], "status": "conflict", "category": "attribute", "severity": "low", "explanation": "bounded test evidence", "evidence": [{"chapter_id": evidence["chapter_id"], "span_id": evidence["id"], "relation": "contradicts", "sufficiency": "sufficient", "related_memory_ids": []}]})
        return ProviderResult({"issues": issues}, input_tokens=100, output_tokens=10, latency_ms=7, cost_cny=0.1)


class InvalidSecondBatchProvider(BatchProvider):
    """Returns a billed but invalid second batch; no client or network is used."""
    def evaluate(self, request):
        result = super().evaluate(request)
        if len(self.calls) == 2:
            return ProviderResult({"issues": [{"claim_span_id": "unknown"}]}, input_tokens=100, output_tokens=10, latency_ms=7, cost_cny=0.1)
        return result


class InvalidSecondMemoryBatchProvider(BatchProvider):
    def evaluate(self, request):
        result = super().evaluate(request)
        if request.get("task") == "memory_initialization" and len(self.calls) in {2,3,4}:
            source = request["sources"][0]
            return ProviderResult({"candidates": [{"memory_type": "static_canon", "subject": "invalid", "predicate": "fact", "value": "invalid", "chapter_id": source["chapter_id"], "source_span_id": "forged-chunk-id"}]}, input_tokens=100, output_tokens=10, latency_ms=7, cost_cny=0.1)
        return result


class EmptySecondMemoryBatchProvider(BatchProvider):
    def evaluate(self, request):
        result = super().evaluate(request)
        if request.get("task") == "memory_initialization" and len(self.calls) in {2,3,4}:
            return ProviderResult({"candidates": []}, input_tokens=100, output_tokens=10, latency_ms=7, cost_cny=0.1)
        return result


class OverBudgetSecondMemoryBatchProvider(BatchProvider):
    def evaluate(self, request):
        result = super().evaluate(request)
        if request.get("task") == "memory_initialization" and len(self.calls) == 2:
            return ProviderResult(result.payload, input_tokens=7001, output_tokens=1000, latency_ms=7, cost_cny=0.1)
        return result


class RepairableSecondMemoryBatchProvider(BatchProvider):
    def evaluate(self, request):
        result=super().evaluate(request)
        if request.get("task") == "memory_initialization" and len(self.calls)==2:
            return ProviderResult({"candidates": []},input_tokens=100,output_tokens=10,latency_ms=7,cost_cny=0.1)
        return result


class RepairableOnSecondRepairMemoryBatchProvider(BatchProvider):
    def evaluate(self, request):
        result=super().evaluate(request)
        if request.get("task") == "memory_initialization" and len(self.calls) in {2,3}:
            return ProviderResult({"candidates": []},input_tokens=100,output_tokens=10,latency_ms=7,cost_cny=0.1)
        return result


class ProviderFailureSecondMemoryBatchProvider:
    available = True
    label = "stage11-provider-failure"
    model_label = "stage11-provider-failure-model"

    def __init__(self):
        self.calls = []

    def evaluate(self, request):
        self.calls.append(request)
        if len(self.calls) == 2:
            raise ProviderFailure()
        source_item = request["sources"][0]
        return ProviderResult({"candidates": [{"memory_type": "static_canon", "subject": source_item["id"], "predicate": "fact", "value": "confirmed", "chapter_id": source_item["chapter_id"], "source_span_id": source_item["id"]}]}, input_tokens=100, output_tokens=10, latency_ms=7, cost_cny=0.1)


class InvalidJsonSecondMemoryBatchProvider:
    available = True
    label = "stage11-invalid-json"
    model_label = "stage11-invalid-json-model"

    def __init__(self): self.calls = []

    def evaluate(self, request):
        self.calls.append(request)
        if len(self.calls) == 2:
            raise ProviderInvalidJson(100, 10, 0.1, 7, "length")
        source_item = request["sources"][0]
        return ProviderResult({"candidates": [{"memory_type": "static_canon", "subject": source_item["id"], "predicate": "fact", "value": "confirmed", "chapter_id": source_item["chapter_id"], "source_span_id": source_item["id"]}]}, input_tokens=100, output_tokens=10, latency_ms=7, cost_cny=0.1)


class InvalidJsonSecondContinuityProvider:
    available = True
    label = "stage11-invalid-json-continuity"
    model_label = "stage11-invalid-json-continuity-model"

    def __init__(self): self.calls = []

    def evaluate(self, request):
        self.calls.append(request)
        if len(self.calls) == 2:
            raise ProviderInvalidJson(100, 10, 0.1, 7, "length")
        claim = request["claims"][0]; evidence = claim["allowed_evidence"][0]
        return ProviderResult({"issues": [{"claim_span_id": claim["id"], "status": "conflict", "category": "attribute", "severity": "low", "explanation": "bounded test evidence", "evidence": [{"chapter_id": evidence["chapter_id"], "span_id": evidence["id"], "relation": "contradicts", "sufficiency": "sufficient", "related_memory_ids": []}]}]}, input_tokens=100, output_tokens=10, latency_ms=7, cost_cny=0.1)


class Stage11BoundedContextTests(unittest.TestCase):
    def long_source(self, chars=18000, sentence=True):
        body = (("甲" * 599 + "。") * (chars // 600 + 1))[:chars] if sentence else "𠮷" * chars
        return {"id": "span-long", "chapter_id": "chapter-long", "chapter_number": 1, "chapter_title": "Long", "label": "import", "body": body}

    def test_provider_budget_rejects_before_factory_or_network(self):
        constructed = 0
        provider = object.__new__(DeepSeekProvider)
        provider.model = "unit"; provider.base_url = "https://unit.invalid"; provider.api_key = "unit"; provider.enabled = True
        provider.request_attempts = 0; provider.successful_responses = 0
        def factory():
            nonlocal constructed
            constructed += 1
            raise AssertionError("budget guard must run before client construction")
        provider._factory = factory
        with self.assertRaises(InputBudgetExceeded):
            provider.evaluate({"task": "memory_initialization", "source_revision": 1, "sources": [source(1, 7000)], "output_schema": {"candidates": []}})
        self.assertEqual((constructed, provider.request_attempts), (0, 0))

    def test_provider_request_cap_rejects_before_next_network_call(self):
        provider = object.__new__(DeepSeekProvider)
        provider.model = "unit"; provider.base_url = "https://unit.invalid"; provider.api_key = "unit"; provider.enabled = True
        provider.request_attempts = 36; provider.successful_responses = 36; provider.request_cap = 36; provider.max_retries = 0
        provider._factory=lambda: self.fail("request cap must stop before client construction")
        with self.assertRaises(ProviderFailure):
            provider.evaluate({"draft":{"id":"d","revision":1,"body":"short"},"claims":[],"memory":[],"output_schema":{"issues":[]}})
        self.assertEqual(provider.request_attempts,36)

    def test_memory_v5_prompt_declares_shared_controlled_predicates_and_hard_output_limits(self):
        engine = MemoryInitializationEngine(BatchProvider())
        request = engine._request([source(1, 20)], 1)
        prompt = memory_initialization_prompt(request)
        payload = json.loads(prompt)
        self.assertIn('"max_candidates":4', prompt)
        self.assertIn('"subject_max_chars":80', prompt)
        self.assertIn('"predicate_max_chars":80', prompt)
        self.assertIn('"value_max_chars":240', prompt)
        self.assertEqual(payload["controlled_predicates"], list(CONTROLLED_PREDICATES))
        self.assertEqual(payload["controlled_predicates"], ["identity", "relationship", "affiliation", "location", "status", "rule", "possession", "event_occurred", "knowledge"])
        self.assertTrue(all(is_controlled_candidate("static_canon", predicate, allow_legacy_alias=False) for predicate in payload["controlled_predicates"]))
        self.assertFalse(is_controlled_candidate("open_thread", "status", allow_legacy_alias=False))
        self.assertFalse(is_controlled_candidate("static_canon", "knows", allow_legacy_alias=False))
        self.assertTrue(is_controlled_candidate("static_canon", "knows"))
        self.assertEqual(engine.provenance()["prompt_version"], "memory-initialization-v8-pro-two-repair")

    def test_memory_v5_validation_rejects_unbounded_candidate_count_and_fields(self):
        source_item = source(1, 20)
        engine = MemoryInitializationEngine(BatchProvider())
        candidate = {"memory_type": "static_canon", "subject": "s" * 80, "predicate": "p" * 80, "value": "v" * 240, "chapter_id": source_item["chapter_id"], "source_span_id": source_item["id"]}
        self.assertEqual(engine.validate({"candidates": [candidate]}, {"sources": [source_item]}), [candidate])
        with self.assertRaises(ValueError): engine.validate({"candidates": [candidate] * 5}, {"sources": [source_item]})
        with self.assertRaises(ValueError): engine.validate({"candidates": [{**candidate, "value": "v" * 241}]}, {"sources": [source_item]})

    def test_memory_v7_validation_reports_field_subcodes_and_only_normalizes_format(self):
        source_item=source(1,20)
        engine=MemoryInitializationEngine(BatchProvider())
        base={"memory_type":"static_canon","subject":"s","predicate":"status","value":"v","chapter_id":source_item["chapter_id"],"source_span_id":source_item["id"]}
        for changed,code,field in (
            ({**base,"memory_type":"fact"},"memory_type_invalid","memory_type"),
            ({**base,"subject":7},"required_field_type_invalid","subject"),
            ({**base,"value":"  "},"required_field_blank","value"),
        ):
            with self.subTest(code=code):
                with self.assertRaises(ValueError) as raised:engine.validate({"candidates":[changed]},{"sources":[source_item]})
                self.assertEqual((str(raised.exception),raised.exception.field),(code,field))
        normalized,events=engine._validate_with_normalization({"candidates":[{**base,"memory_type":" Static-Canon ","subject":" s ","comment":"discard"}]},{"sources":[source_item]})
        self.assertEqual((normalized[0]["memory_type"],normalized[0]["subject"]),("static_canon","s"))
        self.assertEqual(events,{"trimmed_string":2,"memory_type_format":1,"extra_fields_removed":1})

    def test_longform_incremental_retrieval_is_deduped_bounded_and_traceable(self):
        spans=[source(index,18000) for index in range(1,6)]
        memory=[]
        for index in range(67):
            span=spans[index%len(spans)]
            memory.append({"id":f"memory-{index:02d}","memory_type":"static_canon","subject":f"人物{index:02d}","predicate":"status","value":f"历史状态{index:02d}","source_span_id":span["id"]})
        claims=[{"id":f"claim-{index}","text":f"测试记录员{index}移动银色书签。","allowed_evidence":[span for span in spans for _ in range(3)]} for index in (1,2)]
        data={"claims":claims,"memory":memory,"draft":{"id":"draft-long","revision":2,"body":""}}
        engine=ContinuityEngine(BatchProvider()); batches=engine._batches(data)
        self.assertTrue(all(request_prompt_and_budget(batch)[1]<=6000 for batch in batches))
        self.assertTrue(all(len(claim["allowed_evidence"])<=3 for batch in batches for claim in batch["claims"]))
        self.assertTrue(all(len(span["prompt_excerpt"])<=500 for batch in batches for claim in batch["claims"] for span in claim["allowed_evidence"]))
        self.assertTrue(all(len(batch["memory"])<=15 for batch in batches))
        result=engine.execute(data)
        self.assertEqual(result["status"],"completed")
        self.assertEqual(result["retrieval_method_version"],"bounded-lexical-v4-longform")
        self.assertEqual(len(result["retrieval_traces"]),2)
        self.assertTrue(all(len(trace["returned_span_ids"])<=3 and len(trace["returned_span_ids"])==len(set(trace["returned_span_ids"])) for trace in result["retrieval_traces"]))

        delta=MemoryDeltaEngine(BatchProvider())
        request=delta._request({"source_revision":2,"sources":[source(99,100)],"memory":memory})
        self.assertEqual(len(request["memory"]),20)
        self.assertLessEqual(request_prompt_and_budget(request)[1],6000)
        self.assertEqual(delta.provenance()["prompt_version"],"memory-delta-v2-bounded-retrieval")

    def test_provider_uses_2000_output_cap_and_invalid_json_keeps_only_metadata(self):
        posted = []
        class Response:
            def raise_for_status(self): pass
            def json(self): return {"choices": [{"finish_reason": "stop", "message": {"content": '{"candidates":[]}'}}], "usage": {"prompt_tokens": 2, "completion_tokens": 1, "cost_cny": 0.25}}
        class InvalidResponse:
            def raise_for_status(self): pass
            def json(self): return {"choices": [{"finish_reason": "length", "message": {"content": '{"candidates":'}}], "usage": {"prompt_tokens": 3, "completion_tokens": 4, "cost_cny": 0.5}}
        class Client:
            def __init__(self, response): self.response = response
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def post(self, *_args, **kwargs): posted.append(kwargs); return self.response
        provider = object.__new__(DeepSeekProvider)
        provider.model = "unit"; provider.base_url = "https://unit.invalid"; provider.api_key = "unit"; provider.enabled = True
        provider.request_attempts = 0; provider.successful_responses = 0; provider.max_retries = 0; provider._factory = lambda: Client(Response())
        result = provider.evaluate({"task": "memory_initialization", "source_revision": 1, "sources": [source(1, 20)], "output_schema": {"candidates": []}})
        self.assertEqual((posted[0]["json"]["max_tokens"], posted[0]["json"]["response_format"], result.input_tokens, result.output_tokens, result.cost_cny, result.finish_reason), (2000, {"type":"json_object"}, 2, 1, 0.25, "stop"))
        provider._factory = lambda: Client(InvalidResponse())
        with self.assertRaises(ProviderInvalidJson) as raised:
            provider.evaluate({"task": "memory_initialization", "source_revision": 1, "sources": [source(1, 20)], "output_schema": {"candidates": []}})
        error = raised.exception
        self.assertEqual((error.input_tokens, error.output_tokens, error.cost_cny, error.finish_reason, error.cost_available), (3, 4, 0.5, "length", True))
        self.assertIsInstance(error.latency_ms, int)
        self.assertNotIn('{"candidates":', str(error) + repr(vars(error)))

    def test_provider_invalid_json_without_usage_does_not_fabricate_tokens_or_cost(self):
        class Response:
            def raise_for_status(self): pass
            def json(self): return {"choices": [{"finish_reason": "length", "message": {"content": '{'}}]}
        class Client:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def post(self, *_args, **_kwargs): return Response()
        provider = object.__new__(DeepSeekProvider)
        provider.model = "unit"; provider.base_url = "https://unit.invalid"; provider.api_key = "unit"; provider.enabled = True
        provider.request_attempts = 0; provider.successful_responses = 0; provider.max_retries = 0; provider._factory = Client
        with self.assertRaises(ProviderInvalidJson) as raised:
            provider.evaluate({"task": "memory_initialization", "source_revision": 1, "sources": [source(1, 20)], "output_schema": {"candidates": []}})
        error = raised.exception
        self.assertEqual((error.input_tokens, error.output_tokens, error.cost_cny, error.finish_reason, error.cost_available), (None, None, None, "length", False))

    def test_provider_budget_inside_boundary_constructs_only_injected_client(self):
        constructed = 0
        class Response:
            def raise_for_status(self): pass
            def json(self): return {"choices": [{"message": {"content": '{"issues":[]}'}}], "usage": {"prompt_tokens": 2, "completion_tokens": 1}}
        class Client:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def post(self, *_args, **_kwargs): return Response()
        provider = object.__new__(DeepSeekProvider)
        provider.model = "unit"; provider.base_url = "https://unit.invalid"; provider.api_key = "unit"; provider.enabled = True
        provider.request_attempts = 0; provider.successful_responses = 0
        def factory():
            nonlocal constructed
            constructed += 1
            return Client()
        provider._factory = factory
        result = provider.evaluate({"draft": {"id": "d", "revision": 1, "body": "短句。"}, "claims": [], "memory": [], "output_schema": {"issues": []}})
        self.assertEqual((constructed, provider.request_attempts, result.input_tokens, result.output_tokens), (1, 1, 2, 1))

    def test_memory_batches_are_stable_aggregated_and_fail_closed(self):
        data = {"source_revision": 1, "sources": [source(index) for index in range(1, 5)]}
        provider = BatchProvider()
        engine = MemoryInitializationEngine(provider)
        first = engine.execute(data)
        first_boundaries = [[item["id"] for item in request["sources"]] for request in provider.calls]
        provider_again = BatchProvider()
        second = MemoryInitializationEngine(provider_again).execute(data)
        self.assertEqual((first["status"], len(first["candidates"]), first["input_tokens"], first["output_tokens"], first["latency_ms"], first["cost_cny"]), ("completed", 4, 100 * len(first_boundaries), 10 * len(first_boundaries), 7 * len(first_boundaries), 0.1 * len(first_boundaries)))
        self.assertEqual(first_boundaries, [[item["id"] for item in request["sources"]] for request in provider_again.calls])
        failed = MemoryInitializationEngine(BatchProvider(fail_at=2)).execute(data)
        self.assertEqual((failed["status"], failed["error_code"], failed["failure_phase"], failed["failed_batch_ordinal"], failed["total_batches"]), ("failed", "provider_timeout", "provider_request", 2, len(first_boundaries)))

    def test_memory_failure_observability_distinguishes_budget_schema_and_evidence(self):
        data = {"source_revision": 1, "sources": [self.long_source()]}
        cases = (
            (OverBudgetSecondMemoryBatchProvider(), "budget_paused", "post_response_budget"),
            (EmptySecondMemoryBatchProvider(), "empty_candidates", "post_response_validation"),
            (InvalidSecondMemoryBatchProvider(), "evidence_unresolvable", "post_response_validation"),
        )
        for provider,error_code,phase in cases:
            with self.subTest(error_code=error_code):
                result=MemoryInitializationEngine(provider).execute(data)
                expected_calls=4 if error_code in {"empty_candidates","evidence_unresolvable"} else 2
                self.assertEqual((len(provider.calls),result["status"],result["error_code"],result["failure_phase"],result["failed_batch_ordinal"]),(expected_calls,"failed",error_code,phase,2))
                self.assertGreaterEqual(result["total_batches"],2)
                self.assertEqual(result["latency_ms"],7*expected_calls)

    def test_memory_schema_repair_carries_only_safe_context(self):
        data={"source_revision":1,"sources":[self.long_source()]}
        provider=RepairableSecondMemoryBatchProvider()
        result=MemoryInitializationEngine(provider).execute(data)
        self.assertEqual((result["status"],result["schema_repair_attempts"],len(provider.calls)),("completed",1,result["total_batches"]+1))
        repair_request=provider.calls[2]
        self.assertEqual(repair_request["schema_repair"],{"reason_code":"empty_candidates","attempt":1,"global_attempt":1})
        self.assertNotIn("previous_response",repair_request)
        self.assertLessEqual(request_prompt_and_budget(repair_request)[1],6000)
        self.assertEqual(result["repair_events"],[{"batch_ordinal":2,"attempt":1,"batch_attempt":1,"reason_code":"empty_candidates","result":"succeeded"}])
        self.assertEqual(result["validated_batches"],result["total_batches"])
        self.assertGreaterEqual(result["staged_candidate_count"],len(result["candidates"]))

    def test_memory_schema_repair_second_attempt_succeeds_without_semantic_coercion(self):
        data={"source_revision":1,"sources":[self.long_source()]}
        provider=RepairableOnSecondRepairMemoryBatchProvider()
        result=MemoryInitializationEngine(provider).execute(data)
        self.assertEqual((result["status"],result["schema_repair_attempts"],len(provider.calls)),("completed",2,result["total_batches"]+2))
        self.assertEqual([request.get("schema_repair") for request in provider.calls[2:4]],[
            {"reason_code":"empty_candidates","attempt":1,"global_attempt":1},
            {"reason_code":"empty_candidates","attempt":2,"global_attempt":2},
        ])
        self.assertEqual(result["repair_events"],[
            {"batch_ordinal":2,"attempt":1,"batch_attempt":1,"reason_code":"empty_candidates","result":"failed","final_reason_code":"empty_candidates"},
            {"batch_ordinal":2,"attempt":2,"batch_attempt":2,"reason_code":"empty_candidates","result":"succeeded"},
        ])

    def test_memory_schema_repair_is_limited_to_five_global_attempts(self):
        class FiveRepairProvider(BatchProvider):
            def evaluate(self,request):
                self.calls.append(request)
                if "schema_repair" not in request:return ProviderResult({"candidates":[]},input_tokens=1,output_tokens=1,latency_ms=1)
                item=request["sources"][0]
                return ProviderResult({"candidates":[{"memory_type":"static_canon","subject":item["id"],"predicate":"status","value":"ok","chapter_id":item["chapter_id"],"source_span_id":item["id"]}]},input_tokens=1,output_tokens=1,latency_ms=1)
        provider=FiveRepairProvider(); engine=MemoryInitializationEngine(provider)
        requests=[engine._request([source(index,20)],1) for index in range(1,7)]
        engine._batches=lambda data:requests
        result=engine.execute({"source_revision":1,"sources":[source(index,20) for index in range(1,7)]})
        self.assertEqual((result["status"],result["error_code"],result["schema_repair_attempts"],result["validated_batches"],len(provider.calls)),("failed","empty_candidates",5,5,11))
        self.assertTrue(all(event["result"]=="succeeded" and event["batch_attempt"]==1 for event in result["repair_events"]))

    def test_failed_memory_batches_leave_database_candidate_state_unchanged_before_atomic_completion(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="scc-stage11-atomic-"))
        db = V2Database(AppPaths.from_project_root(root, protected_poc_root=root / "protected")); db.initialize()
        registered, _ = db.register({"account_name": "stage11atomic", "display_name": "Stage 11", "password": "stage11-safe-password"}, str(uuid.uuid4()))
        user = registered["user"]["id"]
        imported = "# A\n" + "甲" * 18000
        preview, _ = db.preview_import(user, "atomic.md", imported.encode("utf-8"), str(uuid.uuid4()))
        committed, _ = db.commit_import(user, preview["import_id"], {"confirm": True, "title": "Atomic", "summary": "", "genre": "", "chapter_preview_ids": [item["preview_id"] for item in preview["detected"]["chapters"]]}, str(uuid.uuid4()))
        project = committed["project"]["id"]
        input_data = db.memory_initialization_input(user, project, 1)
        with db.connection() as connection:
            before = tuple(connection.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (project,)).fetchone()[0] for table in ("v2_memory_initializations", "v2_memory_candidates", "v2_memory_candidate_decisions", "v2_memory_records"))
        provider = BatchProvider(fail_at=2)
        failure = MemoryInitializationEngine(provider).execute(input_data)
        with db.connection() as connection:
            after = tuple(connection.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (project,)).fetchone()[0] for table in ("v2_memory_initializations", "v2_memory_candidates", "v2_memory_candidate_decisions", "v2_memory_records"))
        self.assertEqual(len(provider.calls), 2)
        self.assertTrue(all("chunk_id" in call["sources"][0] for call in provider.calls))
        self.assertEqual((failure["status"], failure["error_code"], failure["input_tokens"], failure["output_tokens"], failure["latency_ms"], failure["cost_cny"], before, after), ("failed", "provider_timeout", 100, 10, 7, 0.1, (0, 0, 0, 0), (0, 0, 0, 0)))
        self.assertEqual((failure["failure_phase"],failure["failed_batch_ordinal"],failure["total_batches"],failure["schema_repair_attempts"]),("provider_request",2,len(MemoryInitializationEngine(BatchProvider())._batches(input_data)),0))

    def test_source_chunk_offsets_cover_long_chinese_source_with_bounded_prompts(self):
        source_item = self.long_source()
        engine = MemoryInitializationEngine(BatchProvider())
        chunks = engine.chunk_plan({"source_revision": 1, "sources": [source_item]})
        self.assertEqual(engine.chunking_method_version(), "source-chunk-v4-5800")
        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0]["chunk_start"], 0)
        self.assertEqual(chunks[-1]["chunk_end"], len(source_item["body"]))
        assembled = chunks[0]["body"]
        previous_end = chunks[0]["chunk_end"]
        for chunk in chunks:
            self.assertEqual((chunk["id"], chunk["chapter_id"], chunk["body"]), (source_item["id"], source_item["chapter_id"], source_item["body"][chunk["chunk_start"]:chunk["chunk_end"]]))
            self.assertLessEqual(request_prompt_and_budget(engine._request([chunk], 1))[1], 6000)
            if chunk is not chunks[0]:
                self.assertLessEqual(previous_end - chunk["chunk_start"], 200)
                self.assertGreater(chunk["chunk_end"], previous_end)
                assembled += chunk["body"][previous_end - chunk["chunk_start"]:]
                previous_end = chunk["chunk_end"]
        self.assertEqual(assembled, source_item["body"])

    def test_source_chunk_hard_cuts_unicode_codepoints_and_is_stable(self):
        data = {"source_revision": 1, "sources": [self.long_source(9000, sentence=False)]}
        engine = MemoryInitializationEngine(BatchProvider())
        plans = [engine.chunk_plan(data) for _ in range(3)]
        signatures = [[(item["id"], item.get("chunk_ordinal"), item.get("chunk_start"), item.get("chunk_end")) for item in plan] for plan in plans]
        batches = [[[[item["id"], item.get("chunk_ordinal"), item.get("chunk_start"), item.get("chunk_end")] for item in request["sources"]] for request in run] for run in [engine._batches(data) for _ in range(3)]]
        self.assertTrue(all(signature == signatures[0] for signature in signatures[1:]))
        self.assertTrue(all(boundaries == batches[0] for boundaries in batches[1:]))
        self.assertGreater(len(plans[0]), 1)
        self.assertTrue(all(item["body"] == data["sources"][0]["body"][item["chunk_start"]:item["chunk_end"]] for item in plans[0]))

    def test_source_chunk_overlap_sentence_only_does_not_repeat_previous_end(self):
        body = "甲" * 4000 + "。" + "乙" * 14000
        source_item = {"id": "span-overlap", "chapter_id": "chapter-overlap", "chapter_number": 1, "chapter_title": "Overlap", "label": "import", "body": body}
        engine = MemoryInitializationEngine(BatchProvider())
        plans = [engine.chunk_plan({"source_revision": 1, "sources": [source_item]}) for _ in range(3)]
        signatures = [[(item["chunk_start"], item["chunk_end"]) for item in plan] for plan in plans]
        self.assertTrue(all(signature == signatures[0] for signature in signatures[1:]))
        chunks = plans[0]
        self.assertEqual((chunks[0]["chunk_start"], chunks[-1]["chunk_end"]), (0, len(body)))
        previous_end = chunks[0]["chunk_end"]
        rebuilt = chunks[0]["body"]
        for chunk in chunks:
            self.assertEqual(chunk["body"], body[chunk["chunk_start"]:chunk["chunk_end"]])
            self.assertLessEqual(request_prompt_and_budget(engine._request([chunk], 1))[1], 6000)
            if chunk is not chunks[0]:
                self.assertGreater(chunk["chunk_end"], previous_end)
                self.assertLessEqual(previous_end - chunk["chunk_start"], 200)
                rebuilt += chunk["body"][previous_end - chunk["chunk_start"]:]
                previous_end = chunk["chunk_end"]
        self.assertEqual(rebuilt, body)
        self.assertEqual(engine.provenance()["chunking_method_version"], "source-chunk-v4-5800")

    def test_chunk_prompt_accepts_parent_span_and_rejects_chunk_or_foreign_references(self):
        engine = MemoryInitializationEngine(BatchProvider())
        chunk = engine.chunk_plan({"source_revision": 1, "sources": [self.long_source()]})[0]
        valid = {"memory_type": "static_canon", "subject": "fact", "predicate": "state", "value": "confirmed", "chapter_id": chunk["chapter_id"], "source_span_id": chunk["id"]}
        self.assertEqual(engine.validate({"candidates": [valid]}, {"sources": [chunk]}), [valid])
        for changed in ({**valid, "source_span_id": chunk["chunk_id"]}, {**valid, "source_span_id": "foreign-span"}, {**valid, "chapter_id": "foreign-chapter"}):
            with self.assertRaises(ValueError):
                engine.validate({"candidates": [changed]}, {"sources": [chunk]})

    def test_chunk_overlap_candidates_dedupe_and_invalid_second_chunk_usage_is_aggregated(self):
        data = {"source_revision": 1, "sources": [self.long_source()]}
        deduped = MemoryInitializationEngine(BatchProvider()).execute(data)
        self.assertEqual((deduped["status"], len(deduped["candidates"])), ("completed", 1))
        invalid_provider = InvalidSecondMemoryBatchProvider()
        failed = MemoryInitializationEngine(invalid_provider).execute(data)
        self.assertEqual(len(invalid_provider.calls), 4)
        self.assertEqual((failed["status"], failed["error_code"], failed["input_tokens"], failed["output_tokens"], failed["latency_ms"], failed["cost_cny"],failed["schema_repair_attempts"]), ("failed", "evidence_unresolvable", 400, 40, 28, 0.4,2))
        provider_failure = ProviderFailureSecondMemoryBatchProvider()
        failed_provider = MemoryInitializationEngine(provider_failure).execute(data)
        self.assertEqual((len(provider_failure.calls), failed_provider["status"], failed_provider["error_code"], failed_provider["input_tokens"], failed_provider["output_tokens"], failed_provider["latency_ms"], failed_provider["cost_cny"]), (2, "failed", "provider_error", 100, 10, 7, 0.1))

    def test_invalid_json_second_memory_batch_aggregates_usage_and_keeps_database_unchanged(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="scc-stage11e-atomic-"))
        db = V2Database(AppPaths.from_project_root(root, protected_poc_root=root / "protected")); db.initialize()
        registered, _ = db.register({"account_name": "stage11eatomic", "display_name": "Stage 11E", "password": "stage11-safe-password"}, str(uuid.uuid4()))
        user = registered["user"]["id"]
        preview, _ = db.preview_import(user, "atomic.md", ("# A\n" + "甲" * 18000).encode("utf-8"), str(uuid.uuid4()))
        committed, _ = db.commit_import(user, preview["import_id"], {"confirm": True, "title": "Atomic", "summary": "", "genre": "", "chapter_preview_ids": [item["preview_id"] for item in preview["detected"]["chapters"]]}, str(uuid.uuid4()))
        project = committed["project"]["id"]
        with db.connection() as connection:
            before = tuple(connection.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (project,)).fetchone()[0] for table in ("v2_memory_initializations", "v2_memory_candidates", "v2_memory_candidate_decisions", "v2_memory_records"))
        provider = InvalidJsonSecondMemoryBatchProvider()
        failure = MemoryInitializationEngine(provider).execute(db.memory_initialization_input(user, project, 1))
        with db.connection() as connection:
            after = tuple(connection.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (project,)).fetchone()[0] for table in ("v2_memory_initializations", "v2_memory_candidates", "v2_memory_candidate_decisions", "v2_memory_records"))
        self.assertEqual((len(provider.calls), failure["status"], failure["error_code"], failure["input_tokens"], failure["output_tokens"], failure["latency_ms"], failure["cost_cny"], failure["finish_reason"], failure["cost_available"], before, after), (2, "failed", "invalid_json", 200, 20, 14, 0.2, "length", True, (0, 0, 0, 0), (0, 0, 0, 0)))

    def test_short_source_batches_remain_unchunked(self):
        data = {"source_revision": 1, "sources": [source(index) for index in range(1, 5)]}
        engine = MemoryInitializationEngine(BatchProvider())
        self.assertEqual(engine.chunk_plan(data), data["sources"])
        self.assertTrue(all(all("chunk_id" not in item for item in batch["sources"]) for batch in engine._batches(data)))

    def test_continuity_batches_preserve_order_and_do_not_return_partial_issues(self):
        claims = [{"id": f"claim-{index}", "text": "甲" * 600, "allowed_evidence": [{"id": f"span-{index}", "chapter_id": f"chapter-{index}", "body": "甲" * 2400, "prompt_excerpt": "甲" * 720}]} for index in range(1, 4)]
        data = {"draft": {"id": "draft-1", "revision": 1, "body": "not sent in full"}, "claims": claims, "memory": []}
        provider = BatchProvider()
        result = ContinuityEngine(provider).execute(data)
        self.assertEqual((result["status"], [item["claim_span_id"] for item in result["issues"]]), ("completed", ["claim-1", "claim-2", "claim-3"]))
        self.assertGreaterEqual(len(provider.calls), 2)
        self.assertTrue(all(len(request["draft"]["body"]) < len("甲" * 600 * 3) for request in provider.calls))
        timeout_provider = BatchProvider(fail_at=2)
        failed = ContinuityEngine(timeout_provider).execute(data)
        self.assertEqual((len(timeout_provider.calls), failed["status"], failed["error_code"], failed["input_tokens"], failed["output_tokens"], failed["latency_ms"], failed["cost_cny"]), (2, "timed_out", "provider_timeout", 100, 10, 7, 0.1))

    def test_invalid_second_continuity_batch_aggregates_billed_usage(self):
        claims = [{"id": f"claim-{index}", "text": "甲" * 600, "allowed_evidence": [{"id": f"span-{index}", "chapter_id": f"chapter-{index}", "body": "甲" * 2400, "prompt_excerpt": "甲" * 720}]} for index in range(1, 4)]
        provider = InvalidSecondBatchProvider()
        result = ContinuityEngine(provider).execute({"draft": {"id": "draft-invalid", "revision": 1, "body": ""}, "claims": claims, "memory": []})
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual((result["status"], result["error_code"], result["input_tokens"], result["output_tokens"], result["latency_ms"], result["cost_cny"]), ("failed", "schema_invalid", 200, 20, 14, 0.2))

    def test_invalid_json_second_continuity_batch_aggregates_usage_and_finish_reason(self):
        claims = [{"id": f"claim-{index}", "text": "甲" * 600, "allowed_evidence": [{"id": f"span-{index}", "chapter_id": f"chapter-{index}", "body": "甲" * 2400, "prompt_excerpt": "甲" * 720}]} for index in range(1, 4)]
        provider = InvalidJsonSecondContinuityProvider()
        result = ContinuityEngine(provider).execute({"draft": {"id": "draft-invalid-json", "revision": 1, "body": ""}, "claims": claims, "memory": []})
        self.assertEqual((len(provider.calls), result["status"], result["error_code"], result["input_tokens"], result["output_tokens"], result["latency_ms"], result["cost_cny"], result["finish_reason"], result["cost_available"]), (2, "failed", "invalid_json", 200, 20, 14, 0.2, "length", True))

    def test_second_continuity_batch_timeout_finishes_run_without_partial_persistence(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="scc-stage11-run-atomic-"))
        db = V2Database(AppPaths.from_project_root(root, protected_poc_root=root / "protected")); db.initialize()
        registered, _ = db.register({"account_name": "stage11run", "display_name": "Stage 11", "password": "stage11-safe-password"}, str(uuid.uuid4()))
        user = registered["user"]["id"]; project = registered["onboarding"]["tutorial"]["project_id"]
        draft = db.project(user, project)["current_draft"]
        body = "甲" * 600 + "。" + "乙" * 600 + "。" + "丙" * 600 + "。"
        patched, _ = db.patch_draft(user, project, draft["id"], {"title": "Stage 11 bounded", "body": body, "base_revision": draft["revision"]}, str(uuid.uuid4()))
        run, _, _ = db.create_run(user, project, {"draft_id": draft["id"], "draft_revision": patched["revision"]}, str(uuid.uuid4()), ContinuityEngine(BatchProvider()).provenance())
        input_data = db.run_input(project, run["run_id"])
        with db.connection() as connection:
            span = dict(connection.execute("SELECT id,chapter_id,body FROM v2_source_spans WHERE project_id=? ORDER BY id LIMIT 1", (project,)).fetchone())
            before = tuple(connection.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (project,)).fetchone()[0] for table in ("v2_issues", "v2_evidence", "v2_decisions", "v2_change_sets", "v2_memory_records"))
        for claim in input_data["claims"]:
            claim["allowed_evidence"] = [{**span, "prompt_excerpt": "甲" * 720}]
        provider = BatchProvider(fail_at=2)
        result = ContinuityEngine(provider).execute(input_data)
        db.finish_run(project, run["run_id"], result)
        with db.connection() as connection:
            after = tuple(connection.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (project,)).fetchone()[0] for table in ("v2_issues", "v2_evidence", "v2_decisions", "v2_change_sets", "v2_memory_records"))
            stored = connection.execute("SELECT status,error_code FROM v2_runs WHERE id=?", (run["run_id"],)).fetchone()
        self.assertEqual((len(provider.calls), result["status"], result["error_code"], stored["status"], stored["error_code"], after), (2, "timed_out", "provider_timeout", "timed_out", "provider_timeout", before))

    def test_single_oversized_claim_and_excerpt_are_bounded(self):
        data = {"draft": {"id": "draft-2", "revision": 1, "body": ""}, "claims": [{"id": "oversized", "text": "甲" * 7000, "allowed_evidence": []}], "memory": []}
        provider = BatchProvider()
        self.assertEqual(ContinuityEngine(provider).execute(data)["error_code"], "input_budget_exceeded")
        self.assertEqual(provider.calls, [])
        excerpt = V2Database._bounded_excerpt("x" * 1000 + "命中词" + "y" * 1000, {"命中词"}, limit=120)
        self.assertLessEqual(len(excerpt), 122)
        self.assertIn("命中词", excerpt)


if __name__ == "__main__":
    unittest.main()
