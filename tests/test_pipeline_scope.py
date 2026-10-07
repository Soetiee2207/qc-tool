"""Business generation owns obligation coverage; legacy scope is explicit."""
import json
import yaml

from qctool.cli import main
from qctool.cli_run import preflight, build_summary
from qctool.cli import build_parser
from qctool.execute.runner import run_cases, HttpSession
from qctool.testcase import TestCase, Step, StepKind
from tests.test_pipeline_generation import setup, route_case, BASE
import qctool.pipeline as pipeline


def test_business_excludes_seeds_from_generation_but_retains_artifact(monkeypatch,tmp_path):
    seed=route_case();cfg=setup(monkeypatch,tmp_path,cases=[seed],web_url=BASE)
    cfg.generation_profile='business'
    from qctool.ui.crawl import UIMap, PageMap
    import qctool.ui as ui
    monkeypatch.setattr(ui,'crawl',lambda *a,**k:UIMap(BASE,'recorded',[PageMap(BASE+'/login','Login')]))
    original=pipeline.run_generation;seen=[]
    def spy(*a,**k):seen.append(k['existing_cases']);return original(*a,**k)
    monkeypatch.setattr(pipeline,'run_generation',spy)
    result=pipeline.run_pipeline(cfg)
    assert result.ok and result.generation_success and seen==[()]
    assert len(result.generation_result.cases)==1
    assert result.case_scopes=={result.generation_result.cases[0].id:'BUSINESS_COVERAGE'}
    legacy=yaml.safe_load(result.legacy_testcases_path.read_text())
    assert legacy['testcases'][0]['id']==seed.id
    scopes=json.loads((result.out_dir/'case-scopes.json').read_text())
    assert scopes['retained_legacy'][0]['scope']=='LEGACY_DIAGNOSTIC'
    assert not scopes['retained_legacy'][0]['selected']


def test_legacy_profile_preserves_original_seed_execution_scope(monkeypatch,tmp_path):
    cfg=setup(monkeypatch,tmp_path,cases=[route_case()])
    cfg.generation_profile='legacy'
    result=pipeline.run_pipeline(cfg)
    assert result.ok and result.generation_success
    assert result.generation_result.history==()
    assert result.case_scopes=={'TC_LOGIN_001':'LEGACY_DIAGNOSTIC'}
    summary=build_summary(result)
    assert summary['diagnostic_counts']['Not Executed']==1
    assert not sum(summary['business_counts'].values())


def test_primary_default_and_explicit_legacy_profile(monkeypatch,tmp_path):
    import qctool.config as config
    monkeypatch.setattr(config,'load_dotenv',lambda *a:None)
    cfg=setup(monkeypatch,tmp_path,cases=[route_case()])
    path=tmp_path/'config.yaml'
    path.write_text(yaml.safe_dump({'docs_dir':str(cfg.docs_dir),'out':{'skip_run':True}}))
    parser=build_parser()
    assert preflight(parser.parse_args(['run','--config',str(path)])).config.generation_profile=='business'
    assert preflight(parser.parse_args(['run','--config',str(path),'--profile','legacy'])).config.generation_profile=='legacy'
    assert pipeline.PipelineConfig.from_file(path).generation_profile=='legacy'  # all/direct compatibility


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
