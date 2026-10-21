"""Business generation owns obligation coverage; legacy scope is explicit."""
import json
import yaml

from qctool.cli import main
from qctool.cli_run import preflight, build_summary
from qctool.cli import build_parser
from qctool.execute.runner import run_cases, HttpSession
from qctool.core.testcase import TestCase, Step, StepKind
from tests.test_pipeline_generation import setup, route_case, BASE
import qctool.pipeline as pipeline


def test_primary_default_and_explicit_legacy_profile(monkeypatch,tmp_path):
    import qctool.config as config
    monkeypatch.setattr(config,'load_dotenv',lambda *a:None)
    cfg=setup(monkeypatch,tmp_path,cases=[route_case()])
    path=tmp_path/'config.yaml'
    path.write_text(yaml.safe_dump({'docs_dir':str(cfg.docs_dir),'out':{'skip_run':True}}))
    parser=build_parser()
    assert preflight(parser.parse_args(['run','--config',str(path)])).config.generation_profile=='agent'
    assert pipeline.PipelineConfig.from_file(path).generation_profile=='agent'  # all/direct use the same authoring path


def test_diagnostic_failure_is_not_reported_as_business_failure(monkeypatch,tmp_path):
    cfg=setup(monkeypatch,tmp_path,cases=[route_case()]);result=pipeline.run_pipeline(cfg)
    case=TestCase('TC_DIAGNOSTIC_001','API','Negative seed','Diagnostic',steps=[
        Step(1,StepKind.WHEN,'http.request',{'method':'GET','path':'/x'}),
        Step(2,StepKind.THEN,'assert.http_status',{'expected':200})])
    monkeypatch.setattr(HttpSession,'request',lambda *a,**kw:{'status':400,'body':{},'raw':'{}','duration_ms':0})
    result.run_result=run_cases([case],HttpSession(BASE))
    result.counts=result.run_result.counts
    result.generation_result=__import__('dataclasses').replace(result.generation_result,cases=(case,))
    result.case_scopes={case.id:'LEGACY_DIAGNOSTIC'}
    summary=build_summary(result)
    assert summary['counts']['Fail']==summary['diagnostic_counts']['Fail']==1
    assert summary['business_counts']['Fail']==0
    assert summary['status']=='DIAGNOSTIC_EXECUTION_FAILED' and summary['exit_code']==1
