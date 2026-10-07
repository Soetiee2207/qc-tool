"""Manual live-model acceptance, fresh local app, no authored testcase/proposal.

uv run python scripts/run_autonomous_acceptance.py --enable-llm
"""
from __future__ import annotations
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
import yaml
from qctool import ingest, generate, render, report
from qctool.coverage import analyze_coverage
from qctool.coverage_plan import plan_coverage
from qctool.generate.loader import load_endpoints
from qctool.generation import run_generation
from qctool.llm_provider import load_llm_provider, LLMConfigurationError
from qctool.test_fixtures import load_fixture_store
from qctool.pipeline import _paths_from_docs
from qctool.ui.crawl import crawl
from qctool.execute.browser import BrowserSession
from qctool.execute.runner import HttpSession, run_cases
from scripts.autonomous_acceptance_app import create_server

SAMPLE=REPO/'samples/acceptance/autonomous'

class AuditedAdapter:
    def __init__(self, provider, stage, calls, persist, store):
        self.provider,self.stage,self.calls,self.persist,self.store=provider,stage,calls,persist,store
    def complete(self,prompt):
        record={'stage':self.stage,'status':'STARTED','prompt':self.store.redact(prompt)}
        self.calls.append(record);self.persist()
        started=time.monotonic()
        client=replace(self.provider,on_response_metadata=lambda item:record.update(item))
        try:
            response=client.complete(prompt)
            record.update(status='COMPLETED',response=self.store.redact(response))
            return response
        except Exception as error:
            record.update(status='FAILED',error_code=getattr(error,'code',type(error).__name__))
            raise
        finally:
            record['duration_seconds']=round(time.monotonic()-started,3);self.persist()


def run_acceptance(out, provider):
    out.mkdir(parents=True,exist_ok=True)
    server=create_server();thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    env_names=('ACCEPTANCE_EMAIL','ACCEPTANCE_PASSWORD','ACCEPTANCE_WRONG_PASSWORD')
    old={name:os.environ.get(name) for name in env_names}
    # Ephemeral runtime credentials; never written to fixture YAML or source docs.
    os.environ.update(dict(zip(env_names,(secrets.token_hex(8)+'@example.test',secrets.token_urlsafe(20),secrets.token_urlsafe(20)))))
    packet={'status':'RUNNING','base_url':base,'model':provider.model,'provider':provider.base_url,'calls':[],'fresh_account_count':len(server.users)}
    store=None
    def persist():
        safe=store.redact(packet) if store else packet
        encoded=json.dumps(safe,ensure_ascii=False,indent=2).replace(provider.api_key,'[REDACTED]')
        (out/'acceptance.json').write_text(encoded,encoding='utf-8')
    try:
        policy=yaml.safe_load((SAMPLE/'policy.yaml').read_text().replace('APPLICATION_BASE',base))
        store=load_fixture_store(policy)
        (out/'policy.yaml').write_text(yaml.safe_dump(policy,allow_unicode=True),encoding='utf-8')
        document=ingest.ingest_feature(SAMPLE,feature='autonomous');ingest.write_yaml(document,out/'requirements.yaml')
        spec=yaml.safe_load((SAMPLE/'openapi.yaml').read_text());spec['servers']=[{'url':base}]
        (out/'openapi.yaml').write_text(yaml.safe_dump(spec),encoding='utf-8')
        endpoints,_,_=load_endpoints(out/'openapi.yaml')
        before=analyze_coverage(document["requirements"],(),flows=document.get("flows"))
        logical=plan_coverage(before,module='AUTONOMOUS')
        packet.update(coverage_before=before.to_dict() if hasattr(before,'to_dict') else {},logical_cases=[c.to_dict() for c in logical.cases])
        # Source routes only; no actions during bootstrap. Dynamic alerts absent.
        ui=crawl(base,anonymous_paths=_paths_from_docs(out/'requirements.yaml'),follow_links=False,wait_ms=100,timeout_ms=8000)
        ui.save(out/'ui-map.yaml')
        persist()
        result=run_generation(document,ui_map=ui,endpoints=endpoints,fixture_store=store,
            resolution_llm=AuditedAdapter(provider,'resolution',packet['calls'],persist,store),
            exploration_llm=AuditedAdapter(provider,'exploration',packet['calls'],persist,store),
            base_url=base,module='AUTONOMOUS',max_passes=1,max_cycles=3,
            allow_provisioning=True,environment='local')
        payload=store.redact(result.to_dict());(out/'generation.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        cases=list(result.cases)
        generate.write_cases(cases,out/'testcases.yaml',{'sources':document['sources'],'unverifiable':[], 'warnings':document['warnings']})
        render.render(cases,out/'testcases.xlsx',environment='fresh local acceptance')
        with BrowserSession(base,timeout_ms=8000,evidence_dir=out/'evidence',trace=True) as browser:
            execution=run_cases(cases,HttpSession(base),browser=browser,fixture_store=store)
        report.write_json(execution,out/'results.json');report.write_csv(execution,out/'results.csv')
        report.write_junit(execution,out/'junit.xml');report.render_markdown(execution,out/'report.md')
        render.fill_results(out/'testcases.xlsx',execution)
        packet.update(generation_status=result.status.value,generation_success=result.success,coverage_after=result.coverage.to_dict(),
            executable_case_ids=[c.id for c in result.executable_cases],
            unresolved_case_ids=[c.id for c in result.unresolved_cases],
            results=execution.to_dict(),safe_server_calls=server.calls)
        links={link.obligation.source.source_id:link.testcase_id for entry in result.history if entry.resolution
               for link in entry.resolution.audit}
        actual={c.case_id:c.status for c in execution.cases}
        packet['scenario_results']={source:actual.get(case_id,'Not Executed') for source,case_id in links.items()}
        # Minimum requested proof, not generation success or fabricated Pass.
        minimum=all(packet['scenario_results'].get(source)=='Pass' for source in ('AC-autonomous-001-1','AC-autonomous-001-2'))
        cycles=[c for entry in result.history if entry.resolution for record in entry.resolution.case_results
                if record.resolution for c in record.resolution.cycles]
        explored=any(c.exploration_execution and c.exploration_execution.successful_requests for c in cycles)
        provisioned=any(record.resolution and record.resolution.test_data_preparation and
            record.resolution.test_data_preparation.provisioning_attempted
            for entry in result.history if entry.resolution for record in entry.resolution.case_results)
        packet.update(minimum_pass=minimum,validated_exploration_executed=explored,provisioning_executed=provisioned,
                      llm_calls=len(packet['calls']),status='PASSED' if minimum and explored and provisioned else 'INCOMPLETE')
    except Exception as error:
        import traceback
        packet.update(status='FAILED',error_code=type(error).__name__,error_frames=[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name} for f in traceback.extract_tb(error.__traceback__)])
        # Controlled local diagnostics only; do not persist arbitrary provider/body errors.
    finally:
        persist();server.shutdown();server.server_close();thread.join(timeout=5)
        for name,value in old.items():
            if value is None:os.environ.pop(name,None)
            else:os.environ[name]=value
    return packet


def main():
    parser=argparse.ArgumentParser(description='Fresh docs -> live DeepSeek -> local Chromium acceptance')
    parser.add_argument('--enable-llm',action='store_true')
    parser.add_argument('--out',type=Path,default=REPO/'artifacts/autonomous-acceptance')
    args=parser.parse_args()
    if not args.enable_llm:print('SKIPPED: --enable-llm required; no model/browser calls');return 2
    try:provider=replace(load_llm_provider(),timeout=90)
    except LLMConfigurationError as error:print(str(error));return 2
    result=run_acceptance(args.out,provider)
    print(json.dumps({key:result.get(key) for key in ('status','model','llm_calls','generation_status','scenario_results','error_code')},ensure_ascii=False))
    return 0 if result['status']=='PASSED' else 1

if __name__=='__main__':raise SystemExit(main())
