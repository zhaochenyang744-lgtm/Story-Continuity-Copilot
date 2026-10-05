from __future__ import annotations

import json
import pathlib
import tempfile
import threading
import unittest
import uuid
from dataclasses import replace

import httpx
from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.operations import usage as operations_usage
from app.provider import DeepSeekProvider, ProviderDispatchDenied, ProviderInvalidJson
from app.stage13 import Stage13Settings, UsageGuardProvider, provider_usage


class DispatchQuotaTests(unittest.TestCase):
    def _service(self, attempts: int):
        root=pathlib.Path(tempfile.mkdtemp(prefix="scc-legacy-dispatch-"))
        provider=object.__new__(DeepSeekProvider)
        provider.enabled=True
        provider.model="test-model"
        provider.base_url="https://unit.invalid"
        provider.api_key="fake-test-key"
        provider.request_attempts=0
        provider.successful_responses=0
        provider.request_cap=None
        provider.max_retries=1
        settings=replace(Stage13Settings.for_test(),registered_provider_attempts=attempts)
        app=create_app(AppPaths.from_project_root(root,protected_poc_root=root/"protected"),provider=provider,settings=settings,executor=lambda fn,*args:fn(*args))
        client=TestClient(app)
        registered=client.post("/api/auth/register",headers={"Idempotency-Key":str(uuid.uuid4())},json={"account_name":"quota-author","display_name":"Author","password":"safe-test-password","recovery_email":"quota@example.test"})
        self.assertEqual(registered.status_code,201,registered.text)
        user_id=registered.json()["data"]["user"]["id"]
        reservation=app.state.stage13.reserve_workflow(user_id,None,"quota-test")
        project_id=registered.json()["data"]["onboarding"]["tutorial"]["project_id"]
        return app,provider,user_id,reservation,client,project_id

    def test_timeout_retry_counts_each_actual_post_and_keeps_unknown_cost(self):
        app,provider,user_id,reservation,_client,_project_id=self._service(2)
        posted=[]
        class Response:
            def raise_for_status(self):pass
            def json(self):return {"choices":[{"message":{"content":'{"issues":[]}'}}],"usage":{"prompt_tokens":11,"completion_tokens":7,"cost_cny":0.2}}
        class Client:
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def post(self,*_args,**_kwargs):
                posted.append(1)
                if len(posted)==1:raise httpx.ReadTimeout("simulated timeout")
                return Response()
        provider._factory=Client
        guarded=UsageGuardProvider(provider,app.state.stage13)
        with provider_usage(user_id,reservation):
            result=guarded.evaluate({"draft":{"id":"d","revision":1,"body":"Short."},"claims":[],"memory":[],"output_schema":{"issues":[]}})
        with app.state.database.connection() as c:
            count=c.execute("SELECT COUNT(*) FROM v2_provider_attempts WHERE reservation_id=?",(reservation,)).fetchone()[0]
        self.assertEqual((len(posted),count,provider.request_attempts,result.input_tokens,result.output_tokens,result.cost_cny),(2,2,2,None,None,None))
        self.assertEqual((result.observed_response_input_tokens,result.observed_response_output_tokens,result.observed_response_cost_cny),(11,7,0.2))

    def test_retry_success_persists_unknown_run_totals_without_erasing_observed_response(self):
        app,provider,_user_id,_reservation,client,project_id=self._service(2)
        posted=[]
        class Response:
            # The current (v6) contract needs a claim verdict for every supplied claim.
            def __init__(self,body):self.claims=[claim["id"] for claim in json.loads(body["messages"][0]["content"])["current_claims"]]
            def raise_for_status(self):pass
            def json(self):
                content={"issues":[],"claim_verdicts":[{"claim_span_id":claim,"verdict":"no_issue","basis":"无冲突"} for claim in self.claims]}
                return {"choices":[{"message":{"content":json.dumps(content,ensure_ascii=False)}}],"usage":{"prompt_tokens":11,"completion_tokens":7,"cost_cny":0.2}}
        class Client:
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def post(self,*_args,**kwargs):
                posted.append(1)
                if len(posted)==1:raise httpx.ReadTimeout("response lost after dispatch")
                return Response(kwargs["json"])
        provider._factory=Client
        project=client.get(f"/api/projects/{project_id}").json()["data"]
        draft=project["current_draft"]
        created=client.post(f"/api/projects/{project_id}/checks",headers={"Idempotency-Key":str(uuid.uuid4())},json={"draft_id":draft["id"],"draft_revision":draft["revision"]})
        self.assertEqual(created.status_code,202,created.text)
        run_id=created.json()["data"]["run_id"]
        with app.state.database.connection() as c:
            run=dict(c.execute("SELECT status,input_tokens,output_tokens,cost_cny FROM v2_runs WHERE id=?",(run_id,)).fetchone())
        report=operations_usage({"database":app.state.database.paths.database_path,"failure_window_hours":24,"stuck_run_minutes":10})
        self.assertEqual((len(posted),run["status"],run["input_tokens"],run["output_tokens"],run["cost_cny"]),(2,"completed",None,None,None))
        for field in ("input_tokens","output_tokens","cost_cny"):
            self.assertEqual(report["run_observed_metrics"][field]["status"],"unknown")
            self.assertEqual(report["run_observed_metrics"][field]["unknown_run_count"],1)

    def test_timeout_then_invalid_json_keeps_total_unknown_and_response_observation(self):
        app,provider,user_id,reservation,_client,_project_id=self._service(2)
        posted=[]
        class Response:
            def raise_for_status(self):pass
            def json(self):return {"choices":[{"message":{"content":"invalid-json"}}],"usage":{"prompt_tokens":11,"completion_tokens":7,"cost_cny":0.2}}
        class Client:
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def post(self,*_args,**_kwargs):
                posted.append(1)
                if len(posted)==1:raise httpx.ReadTimeout("response lost after dispatch")
                return Response()
        provider._factory=Client
        with provider_usage(user_id,reservation),self.assertRaises(ProviderInvalidJson) as caught:
            UsageGuardProvider(provider,app.state.stage13).evaluate({"draft":{"id":"d","revision":1,"body":"Short."},"claims":[],"memory":[],"output_schema":{"issues":[]}})
        error=caught.exception
        self.assertEqual((len(posted),error.input_tokens,error.output_tokens,error.cost_cny,error.cost_available),(2,None,None,None,False))
        self.assertEqual((error.observed_response_input_tokens,error.observed_response_output_tokens,error.observed_response_cost_cny),(11,7,0.2))

    def test_one_remaining_attempt_blocks_retry_before_second_post(self):
        app,provider,user_id,reservation,_client,_project_id=self._service(1)
        posted=[]
        class Client:
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def post(self,*_args,**_kwargs):
                posted.append(1)
                raise httpx.ReadTimeout("simulated timeout")
        provider._factory=Client
        guarded=UsageGuardProvider(provider,app.state.stage13)
        with provider_usage(user_id,reservation),self.assertRaisesRegex(ProviderDispatchDenied,"provider_attempt_quota_exceeded"):
            guarded.evaluate({"draft":{"id":"d","revision":1,"body":"Short."},"claims":[],"memory":[],"output_schema":{"issues":[]}})
        with app.state.database.connection() as c:
            count=c.execute("SELECT COUNT(*) FROM v2_provider_attempts WHERE reservation_id=?",(reservation,)).fetchone()[0]
        self.assertEqual((len(posted),count,provider.request_attempts),(1,1,1))

    def test_contract_repair_failure_keeps_run_usage_unknown_only_after_attempted_post(self):
        for mode,limit,expected_status,expected_count,unknown in (
            ("repair_timeouts",10,"timed_out",3,True),
            ("repair_retry_denied",2,"failed",2,True),
            ("repair_before_dispatch_denied",1,"failed",1,False),
        ):
            with self.subTest(mode=mode):
                app,provider,user_id,_reservation,client,project_id=self._service(limit)
                posted=[]
                class Response:
                    def __init__(self,content):self.content=content
                    def raise_for_status(self):pass
                    def json(self):return {"choices":[{"message":{"content":self.content}}],"usage":{"prompt_tokens":11,"completion_tokens":7,"cost_cny":0.2}}
                class Client:
                    def __enter__(self):return self
                    def __exit__(self,*_):pass
                    def post(self,*_args,**kwargs):
                        posted.append(1)
                        if len(posted)>1:raise httpx.ReadTimeout("contract repair response lost")
                        prompt=json.loads(kwargs["json"]["messages"][0]["content"])
                        claim=prompt["current_claims"][0]
                        # A claim lists span ids; each span appears once under evidence_spans.
                        source=next(span for span in prompt["evidence_spans"] if span["id"]==claim["allowed_evidence"][0])
                        legacy={"issues":[{"claim_span_id":claim["id"],"status":"conflict","category":"attribute","severity":"low","explanation":"旧格式需要契约修复。","evidence":[{"chapter_id":source["chapter_id"],"span_id":source["id"],"relation":"contradicts","sufficiency":"sufficient","related_memory_ids":[]}]}]}
                        return Response(json.dumps(legacy,ensure_ascii=False))
                provider._factory=Client
                draft=client.get(f"/api/projects/{project_id}").json()["data"]["current_draft"]
                created=client.post(f"/api/projects/{project_id}/checks",headers={"Idempotency-Key":str(uuid.uuid4())},json={"draft_id":draft["id"],"draft_revision":draft["revision"]})
                self.assertEqual(created.status_code,202,created.text)
                run_id=created.json()["data"]["run_id"]
                with app.state.database.connection() as c:
                    run=dict(c.execute("SELECT status,input_tokens,output_tokens,cost_cny FROM v2_runs WHERE id=?",(run_id,)).fetchone())
                    count=c.execute("SELECT COUNT(*) FROM v2_provider_attempts WHERE user_id=?",(user_id,)).fetchone()[0]
                expected=[None,None,None] if unknown else [11,7,0.2]
                self.assertEqual((run["status"],len(posted),count),(expected_status,expected_count,expected_count))
                self.assertEqual([run[field] for field in ("input_tokens","output_tokens","cost_cny")],expected)
                report=operations_usage({"database":app.state.database.paths.database_path,"failure_window_hours":24,"stuck_run_minutes":10})
                for field in ("input_tokens","output_tokens","cost_cny"):
                    self.assertEqual(report["run_observed_metrics"][field]["status"],"unknown" if unknown else "available")

    def test_concurrent_reservations_do_not_exceed_persistent_limit(self):
        app,_provider,user_id,reservation,_client,_project_id=self._service(1)
        barrier=threading.Barrier(3)
        outcomes=[]
        def reserve():
            barrier.wait()
            try:
                app.state.stage13.reserve_provider_attempt(user_id,reservation)
                outcomes.append("ok")
            except Exception as error:
                outcomes.append(getattr(error,"code",type(error).__name__))
        workers=[threading.Thread(target=reserve) for _ in range(3)]
        for worker in workers:worker.start()
        for worker in workers:worker.join()
        self.assertEqual(sorted(outcomes),["ok","provider_attempt_quota_exceeded","provider_attempt_quota_exceeded"])


if __name__=="__main__":unittest.main()
