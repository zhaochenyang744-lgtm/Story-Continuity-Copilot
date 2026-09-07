"""Independent local acceptance app for the v1.4 author-context candidate."""
import os
from pathlib import Path

from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderResult
from app.stage13 import Stage13Settings


class CandidateProvider:
    available = True
    label = "v140-deterministic-local-stub"
    model_label = "v140-deterministic-local-stub"

    def evaluate(self, request):
        if request.get("task") != "author_material_comparison":
            return ProviderResult(payload={"issues": []})
        material=request["comparison"]["material"]
        passage=request["comparison"]["passage"]
        return ProviderResult(payload={
            "assessment":"plan_deviation" if material["nature"]=="plan" else "possible_tension",
            "explanation":"独立候选环境的确定性桩结果，仅验证真实服务链路与证据绑定。",
            "evidence":[{"source_type":"author_material","source_id":material["id"]},{"source_type":"source_span","source_id":passage["id"]}],
        },input_tokens=12,output_tokens=18,latency_ms=1)


candidate_root = Path(os.environ["V140_CANDIDATE_ROOT"]).resolve()
app = create_app(
    AppPaths.from_project_root(candidate_root, protected_poc_root=candidate_root / "protected"),
    provider=CandidateProvider(),
    settings=Stage13Settings.from_env(),
)
