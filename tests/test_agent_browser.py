"""Live locator proof without ever feeding assertion values back to the agent."""
import pytest
from qctool.agent.tools import AgentTools
from qctool.agent.safety import SafetyPolicy
from qctool.agent.gate import draft_case
from qctool.execute.runner import HttpSession,run_case
from tests.test_browser import HAVE_BROWSER, site

pytestmark=[pytest.mark.playwright,pytest.mark.skipif(not HAVE_BROWSER,reason='Chromium not installed')]


def test_live_snapshot_and_fresh_dry_run_keep_bug_for_runner(site):
    intent={'id':'AC:then','req_id':'AC','given':'anonymous','when':'Open /','expected':'URL /wrong'}
    tools=AgentTools(intent,'TC_AGENT_001','AGENT',SafetyPolicy(site))
    try:
        observed=tools.call('browser_observe',{'url':'/'})
        assert observed.get('url') and 'aria' in observed
        raw={'title':'Wrong documented URL','steps':[
            {'seq':1,'kind':'given','action':'ui.session','args':{'mode':'anonymous'}},
            {'seq':2,'kind':'when','action':'ui.goto','args':{'url':'/'}},
            {'seq':3,'kind':'then','action':'assert.url_matches','args':{'pattern':'/wrong$'},'source':{'req_id':'AC','quote':'URL /wrong'}}]}
        assert tools.call('draft_case',raw)['ok']
        result=tools.call('dry_run',{})
        assert result['ok'] and 'actual' not in str(result)
        assert tools.ready.steps[-1].args['pattern']=='/wrong$'
        session=HttpSession(site)
        try:
            runtime=run_case(tools.ready,session,browser=tools.browser)
            assert runtime.status=='Fail'
        finally:session.close()
    finally:tools.close()


def test_public_pipeline_replay_does_not_fit_planted_ui_bug(site,tmp_path):
    import json
    from qctool.pipeline import PipelineConfig,run_pipeline
    docs=tmp_path/'docs';docs.mkdir()
    (docs/'urd.md').write_text('''---
type: urd
feature: local
status: draft
---
# Local
### US-001 — Dialog
**As a** user
**I want** open a dialog
**So that** validation is enforced
**Acceptance Criteria**
| ID | Given | When | Then |
|---|---|---|---|
| AC-001-1 | Anonymous | Open /; activate Thêm dự án | Save control is disabled |
''')
    class Replay:
        def chat(self,messages,tools,**kwargs):
            first=tools[0]['function']['name']
            if first=='design_tests':
                intent=json.loads(messages[-1]['content'])[0]
                name='design_tests';args={'intents':[{'id':intent['id'],'title':'Disabled Save','source_quote':intent['expected']}]}
            else:
                intent=json.loads(messages[1]['content'])['intent']
                name='draft_case';args={'title':'Disabled Save','steps':[
                    {'seq':1,'kind':'given','action':'ui.session','args':{'mode':'anonymous'}},
                    {'seq':2,'kind':'when','action':'ui.goto','args':{'url':'/'}},
                    {'seq':3,'kind':'when','action':'ui.click','args':{'target':'btn-add'}},
                    {'seq':4,'kind':'then','action':'assert.disabled','args':{'target':'btn-save'},
                     'source':{'req_id':intent['req_id'],'quote':intent['expected']}}]}
            return {'role':'assistant','content':None,'tool_calls':[{'id':name,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}
    cfg=PipelineConfig(docs_dir=docs,feature='local',module='LOCAL',web_url=site,base_url=site,
        auth_mode='manual',out_dir=tmp_path/'out',headless=True,timeout_seconds=3)
    result=run_pipeline(cfg,resolution_llm=Replay())
    assert result.ok,result.error
    assert len(result.generation_result.executable_cases)==1
    assert result.generation_result.executable_cases[0].generation_status=='needs_review'
    assert result.counts['Fail']==1 and result.counts['Pass']==0
    assert result.generation_result.agent_history[0].dry_run_passed
    assert result.report_path.is_file() and result.xlsx_path.is_file()


def test_anonymous_first_step_clears_preloaded_local_storage_on_blank_page(site,tmp_path):
    import json
    from qctool.execute.browser import BrowserSession
    state=tmp_path/'state.json'
    state.write_text(json.dumps({'cookies':[],'origins':[{'origin':site,'localStorage':[{'name':'session-marker','value':'local-test'}]}]}))
    with BrowserSession(site,storage_state=state,authenticated=True,headless=True,timeout_ms=3000) as browser:
        browser.start_case('TC_SESSION_001')
        assert browser.page.url=='about:blank'
        browser.set_session({'mode':'anonymous'})
        browser.goto('/ui')
        assert browser.page.evaluate('localStorage.getItem("session-marker")') is None
