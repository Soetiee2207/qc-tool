from copy import deepcopy
from dataclasses import replace
import json

from qctool.executability import analyze_executability
from qctool.resolution_context import build_resolution_context
from qctool.testcase import Step, StepKind, TestCase
from qctool.ui.crawl import UIMap, PageMap, Element
from qctool.semantic_ir import (parse_semantics, validate_semantics, meanings_for_step,
                                grounded_proposal, source_authorized_routes)
from qctool.proposal_validation import validate_resolution_proposal, ValidationIssue
from qctool.evidence_needs import rejection_needs
from qctool.gap_routing import route_gaps
from qctool.resolution_loop import _evidence_facts

BASE = 'https://app.test'


def inputs(text='Press Continue in the form', then='URL /next'):
    case = TestCase(id='TC_GENERIC_001', module='GENERIC', title='Continue', objective='Continue',
                    traces_to=['AC-1'], source_quote=text+'; '+then, execution='manual', steps=[
                        Step(1, StepKind.WHEN, 'perform.unmapped', {'description': text}),
                        Step(2, StepKind.THEN, 'assert.unmapped', {'expected': then})])
    req = {'id':'AC-1', 'when':text, 'then':then, 'given':''}
    ui = UIMap(BASE, 'now', [PageMap(BASE+'/start','Start',elements=[
        Element('continue','button','Continue','button',test_id='continue-submit'),
        Element('nav','link','Continue','a',test_id='continue-link')]),
        PageMap(BASE+'/next','Next')])
    ctx = build_resolution_context(case, analyze_executability(case).gaps, requirements=[req], ui_map=ui)
    # Source context selection intentionally omits unspecified pages.
    ctx = replace(ctx, observations={'ui_pages':[{'url':p.url,'elements':[e.to_dict() for e in p.elements]} for p in ui.pages]})
    return case,ctx


def normalization(text):
    clauses = [{'step_seq':1,'clause_index':i,'source_text':c.strip(),
                'atoms':[{'kind':'activate','args':{'label':'Continue','role':'button'}}]}
               for i,c in enumerate(text.split(';'))]
    return parse_semantics({'clauses':clauses})


def test_paraphrases_same_intent_and_role_grounding():
    for text in ('Click Continue', 'Press Continue in the form', 'Activate Continue control'):
        case,ctx=inputs(text); snapshot=deepcopy((case,ctx))
        norm,issues=validate_semantics(normalization(text),ctx)
        assert norm.clauses and not any(i.step_seq==1 for i in issues)
        ctx2=replace(ctx,semantics=norm.to_dict())
        proposal=grounded_proposal(case,ctx2)
        result=validate_resolution_proposal(proposal,ctx2,case)
        assert len(result.valid_changes)==1
        assert result.valid_changes[0].args['target']=='continue-submit'
        assert (case,ctx)==snapshot


def test_ambiguous_controls_not_chosen():
    case,ctx=inputs(); norm,_=validate_semantics(normalization(case.steps[0].args['description']),ctx)
    observations=deepcopy(ctx.observations)
    observations['ui_pages'][0]['elements'].append({'test_id':'other','role':'button','name':'Continue'})
    ctx=replace(ctx,semantics=norm.to_dict(),observations=observations)
    assert grounded_proposal(case,ctx).changes==()


def test_source_authorized_unseen_route_and_foreign_rejection():
    case,ctx=inputs('Open /unseen')
    targets=source_authorized_routes(case,ctx,BASE)
    assert [t for t,_ in targets]==[BASE+'/unseen']
    assert not any(t.endswith('/fake') for t,_ in targets)
    case,ctx=inputs('Open https://foreign.test/path')
    assert source_authorized_routes(case,ctx,BASE)==[]


def test_compound_order_completeness_and_wrong_route():
    case,ctx=inputs('Click Continue; open /next')
    raw={'clauses':[{'step_seq':1,'clause_index':0,'source_text':'Click Continue','atoms':[{'kind':'activate','args':{'label':'Continue'}}]},
                    {'step_seq':1,'clause_index':1,'source_text':'open /next','atoms':[{'kind':'navigate','args':{'route':'/next'}}]}]}
    norm,issues=validate_semantics(parse_semantics(raw),ctx)
    meanings=meanings_for_step(case.steps[0],replace(ctx,semantics=norm.to_dict()))
    assert [m['action'] for m in meanings]==['ui.click','ui.goto']
    raw['clauses'].pop()
    norm,issues=validate_semantics(parse_semantics(raw),ctx)
    assert not norm.clauses
    assert any(i.code=='SEMANTIC_CLAUSE_INCOMPLETE' for i in issues)


def test_negation_and_invented_outcome_rejected():
    case,ctx=inputs(then='URL not /next')
    raw={'clauses':[{'step_seq':2,'clause_index':0,'source_text':'URL not /next','atoms':[{'kind':'url','args':{'route':'/next'}}]}]}
    assert not validate_semantics(parse_semantics(raw),ctx)[0].clauses


def test_rejection_routes_evidence_and_duplicate_is_not_progress():
    case,ctx=inputs()
    norm,_=validate_semantics(normalization(case.steps[0].args['description']),ctx)
    from qctool.semantic_ir import normalize_explicit_identifiers, merge_semantics
    ctx=replace(ctx,semantics=merge_semantics(norm.to_dict(), normalize_explicit_identifiers(ctx).to_dict()))
    needs=rejection_needs([ValidationIssue('UI_EVIDENCE_NOT_FOUND','missing',step_seq=1)],ctx)
    ctx2=replace(ctx,evidence_needs=needs)
    assert route_gaps(case,ctx2,base_url=BASE).selected_capability=='exploration'
    again=replace(ctx2,evidence_needs=rejection_needs([ValidationIssue('UI_EVIDENCE_NOT_FOUND','missing',step_seq=1)],ctx2))
    assert _evidence_facts(again)==_evidence_facts(ctx2)


def test_normalization_parser_rejects_extra_fields():
    import pytest
    from qctool.llm_resolution import LLMResponseError, parse_resolution_proposal
    with pytest.raises(LLMResponseError):
        parse_resolution_proposal(json.dumps({'testcase_id':'TC_GENERIC_001','changes':[], 'unresolved':[],
            'semantic':{'clauses':[{'step_seq':1,'clause_index':0,'source_text':'Click Continue','atoms':[], 'target':'fake'}]}}))


def test_normalization_only_cycle_grounds_without_second_model_call():
    from qctool.resolution_cycle import run_resolution_cycle
    case,ctx=inputs('Press Continue in the form')
    raw={'testcase_id':case.id,'changes':[], 'unresolved':[], 'semantic':{'clauses':[
        {'step_seq':1,'clause_index':0,'source_text':'Press Continue in the form','atoms':[{'kind':'activate','args':{'label':'Continue','role':'button'}}]}]}}
    class Model:
        calls=0
        def complete(self,prompt):
            self.calls+=1
            return json.dumps(raw)
    model=Model(); snapshot=deepcopy((case,ctx))
    result=run_resolution_cycle(case,ctx,resolution_llm=model,base_url=BASE)
    assert result.after.executable
    assert model.calls==1
    assert result.semantic_application.applied_changes
    assert (case,ctx)==snapshot


def test_same_clause_omission_and_reordering_are_rejected():
    case,ctx=inputs('Click Continue and open /next')
    raw={'clauses':[{'step_seq':1,'clause_index':0,'source_text':case.steps[0].args['description'],
        'atoms':[{'kind':'activate','args':{'label':'Continue'}}]}]}
    assert not validate_semantics(parse_semantics(raw),ctx)[0].clauses
    raw['clauses'][0]['atoms']=[{'kind':'navigate','args':{'route':'/next'}},{'kind':'activate','args':{'label':'Continue'}}]
    assert not validate_semantics(parse_semantics(raw),ctx)[0].clauses


def test_fabricated_rejection_without_source_normalization_is_not_exploration_work():
    _,ctx=inputs()
    assert rejection_needs([ValidationIssue('UI_EVIDENCE_NOT_FOUND','fabricated',step_seq=1)],ctx)==()


def test_model_cannot_select_arbitrary_ambiguous_semantic_button():
    from qctool.llm_resolution import ResolutionProposal, ProposedChange, EvidenceReference
    case,ctx=inputs(); norm,_=validate_semantics(normalization(case.steps[0].args['description']),ctx)
    observations=deepcopy(ctx.observations)
    observations['ui_pages'][0]['elements'].append({'test_id':'other','role':'button','name':'Continue'})
    ctx=replace(ctx,semantics=norm.to_dict(),observations=observations)
    change=ProposedChange(1,'perform.unmapped',('UNMAPPED_ACTION',),'ui.click',{'target':'continue-submit'},'Choose',
                         (EvidenceReference('ui-map',{'page':BASE+'/start','test_id':'continue-submit'}),))
    result=validate_resolution_proposal(ResolutionProposal(case.id,(change,),()),ctx,case)
    assert not result.valid_changes


def test_invented_alias_and_raw_secret_cannot_acquire_authority():
    from qctool.test_fixtures import FixtureStore
    case,ctx=inputs('Enter email')
    store=FixtureStore({'user':{'email':{'env':'EMAIL'}}},{'AC-1':{'email':'user.email'}},environ={'EMAIL':'PRIVATE-EMAIL'})
    case=store.bind(case)
    ctx=replace(ctx,testcase={**ctx.testcase,'test_data':case.test_data})
    def payload(value):
        return parse_semantics({'clauses':[{'step_seq':1,'clause_index':0,'source_text':'Enter email',
            'atoms':[{'kind':'fill','args':{'field':'email','value':value}}]}]})
    assert validate_semantics(payload('user.email'),ctx,store)[0].clauses
    assert not validate_semantics(payload('invented.email'),ctx,store)[0].clauses
    assert not validate_semantics(payload('PRIVATE-EMAIL'),ctx,store)[0].clauses
    from qctool.llm_resolution import build_resolution_prompt
    assert 'PRIVATE-EMAIL' not in build_resolution_prompt(ctx)


def test_true_no_progress_loop_still_stops_after_identical_need(monkeypatch):
    import qctool.resolution_loop as module
    from types import SimpleNamespace
    case,ctx=inputs(); norm,_=validate_semantics(normalization(case.steps[0].args['description']),ctx)
    enriched=replace(ctx,semantics=norm.to_dict())
    enriched=replace(enriched,evidence_needs=rejection_needs([ValidationIssue('UI_EVIDENCE_NOT_FOUND','missing',step_seq=1)],enriched))
    calls=[]
    def cycle(case,context,**kwargs):
        calls.append(1)
        return SimpleNamespace(case=case,context=enriched,needs_another_cycle=True,audit=(),issues=())
    monkeypatch.setattr(module,'run_resolution_cycle',cycle)
    result=module.run_resolution_loop(case,ctx,max_cycles=5)
    assert result.stop_reason.value=='REPEATED_STATE'
    assert len(calls)==2


def test_unicode_explicit_route_and_anonymous_session_need_no_model():
    from qctool.resolution_cycle import run_resolution_cycle
    case,ctx=inputs('Mở /unseen',then='URL chuyển tới /next')
    case.steps.insert(0,Step(1,StepKind.GIVEN,'perform.unmapped',{'description':'Phiên anonymous chưa đăng nhập'}))
    for i,step in enumerate(case.steps,1):step.seq=i
    req={**ctx.specification['requirements'][0],'given':'Phiên anonymous chưa đăng nhập'}
    ctx=build_resolution_context(case,analyze_executability(case).gaps,requirements=[req])
    ctx=replace(ctx,observations={'ui_pages':[{'url':BASE+'/next','elements':[]}]})
    class NoModel:
        def complete(self,prompt):raise AssertionError('Explicit identifiers need no LLM')
    snapshot=deepcopy((case,ctx))
    result=run_resolution_cycle(case,ctx,resolution_llm=NoModel(),exploration_llm=NoModel(),base_url=BASE)
    assert result.after.executable
    assert [s.action for s in result.case.steps]==['ui.session','ui.goto','assert.url_matches']
    assert result.case.steps[1].args['url']=='/unseen'
    assert (case,ctx)==snapshot


def test_explicit_actor_cannot_disappear_into_session_atom():
    case,ctx=inputs()
    given='anonymous customer'
    case.steps.insert(0,Step(1,StepKind.GIVEN,'perform.unmapped',{'description':given}))
    for i,step in enumerate(case.steps,1):step.seq=i
    ctx=build_resolution_context(case,analyze_executability(case).gaps,requirements=[{
        **ctx.specification['requirements'][0], 'given':given}])
    norm=parse_semantics({'clauses':[{'step_seq':1,'clause_index':0,'source_text':given,
                                    'atoms':[{'kind':'session','args':{'mode':'anonymous'}}]}]})
    assert not validate_semantics(norm,ctx)[0].clauses


def test_api_reference_does_not_authorize_browser_page():
    case,ctx=inputs('POST /api/operation')
    assert source_authorized_routes(case,ctx,BASE)==[]


def test_broad_regex_is_not_a_source_route_literal():
    from qctool.semantic_ir import literals, normalize_explicit_identifiers
    for text in ('URL /next.*', 'URL ^/next$', 'URL /.*'):
        case,ctx=inputs(then=text)
        assert literals(text)==[]
        assert not any(c.step_seq==2 for c in normalize_explicit_identifiers(ctx).clauses)


def test_control_label_words_are_not_sibling_commands():
    for label in ('Enter','Open'):
        text='Press '+label+' in the form'
        case,ctx=inputs(text)
        norm=parse_semantics({'clauses':[{'step_seq':1,'clause_index':0,'source_text':text,
            'atoms':[{'kind':'activate','args':{'label':label,'role':'button'}}]}]})
        result,issues=validate_semantics(norm,ctx)
        assert result.clauses
        assert not any(i.step_seq==1 for i in issues)


def test_control_label_alone_cannot_authorize_activation():
    case,ctx=inputs('Submit button is disabled')
    norm=parse_semantics({'clauses':[{'step_seq':1,'clause_index':0,'source_text':'Submit button is disabled',
        'atoms':[{'kind':'activate','args':{'label':'Submit','role':'button'}}]}]})
    assert not validate_semantics(norm,ctx)[0].clauses


def test_approved_source_prefix_can_inspect_its_unresolved_outcome_only():
    from qctool.exploration_plan import ExplorationPlan, PlannedExploration, ExplorationPurpose, validate_exploration_plan
    from qctool.ui.explore import ExplorationAction
    from qctool.semantic_ir import SemanticClause, SemanticAtom, SemanticNormalization
    text='Press Check in the form'; expected='Show Required'
    case,ctx=inputs(text,expected)
    req=ctx.specification['requirements'][0]
    def note(field):return '[source-clause] '+json.dumps({'requirement_id':req['id'],'field':field,'text':req[field]})
    case.steps=[Step(1,StepKind.GIVEN,'ui.goto',{'url':'/start'}),
                Step(2,StepKind.WHEN,'ui.click',{'target':'check'},note('when')),
                Step(3,StepKind.THEN,'assert.unmapped',{'expected':expected},note('then'))]
    ctx=build_resolution_context(case,analyze_executability(case).gaps,requirements=[req])
    ctx=replace(ctx,observations={'ui_pages':[{'url':BASE+'/start','elements':[{'test_id':'check','id':'check','name':'Check','role':'button','tag':'button'}]}]},
                semantics=SemanticNormalization((SemanticClause(2,0,text,(SemanticAtom('activate',{'label':'Check','role':'button'}),)),)).to_dict())
    request=PlannedExploration('/start',(ExplorationPurpose('UNMAPPED_ACTION',3,'Inspect required outcome','inspect_page'),),
                               actions=(ExplorationAction('check',2),))
    snapshot=deepcopy((case,ctx,request))
    result=validate_exploration_plan(ExplorationPlan(case.id,(request,)),ctx,case,BASE)
    assert result.valid_requests
    assert result.valid_requests[0].grounding[-1]['source_clause']==text
    assert (case,ctx,request)==snapshot
    wrong=replace(request,actions=(ExplorationAction('imaginary',2),))
    assert not validate_exploration_plan(ExplorationPlan(case.id,(wrong,)),ctx,case,BASE).valid_requests
    unrelated=replace(request,purposes=(ExplorationPurpose('UNMAPPED_ACTION',2,'Unrelated','inspect_page'),))
    assert not validate_exploration_plan(ExplorationPlan(case.id,(unrelated,)),ctx,case,BASE).valid_requests


def test_real_plan_validator_accepts_source_route_and_rejects_guessed_route():
    from qctool.exploration_plan import ExplorationPlan, PlannedExploration, ExplorationPurpose, validate_exploration_plan
    case,ctx=inputs('Mở /unseen')
    purpose=ExplorationPurpose('UNMAPPED_ACTION',1,'Inspect source route','inspect_page')
    def validate(target):return validate_exploration_plan(ExplorationPlan(case.id,(PlannedExploration(target,(purpose,)),)),ctx,case,BASE)
    assert validate('/unseen').valid_requests
    assert not validate('/guessed').valid_requests
    assert not validate('https://foreign.test/unseen').valid_requests


def test_observed_text_witness_requires_current_proven_state():
    from qctool.semantic_ir import observed_witnesses
    toast=(None,{'name':'Required','role':'status'})
    alert=(None,{'name':'Required','role':'alert','test_id':'message'})
    assert observed_witnesses([toast,alert],'assert.text',state_proven=True)==[alert]
    assert observed_witnesses([toast,alert],'assert.text')==[toast,alert]
    assert observed_witnesses([toast,alert],'ui.click',state_proven=True)==[toast,alert]
    other=(None,{'name':'Required','role':'alert','test_id':'other'})
    assert observed_witnesses([alert,other],'assert.text',state_proven=True)==[alert,other]


def test_semantic_outcome_uses_stable_witness_and_exact_final_state():
    from tests.test_outcome_grounding import workflow_inputs
    from qctool.semantic_ir import SemanticNormalization, SemanticClause, SemanticAtom
    case,ctx,_=workflow_inputs()
    expected=case.steps[-1].args['expected']
    ctx=replace(ctx,semantics=SemanticNormalization((
        SemanticClause(5,0,expected.split(';')[0].strip(),(SemanticAtom('visible',{'text':'Item ready'}),)),
        SemanticClause(5,1,expected.split(';')[1].strip(),(SemanticAtom('url',{'route':'/details'}),)),
    )).to_dict())
    toast={'name':'Item ready','role':'status','id':'toast'}
    ctx.observations['ui_pages'][-1]['elements'].append(deepcopy(toast))
    ctx.observations['page_states'][-1]['page']['elements'].append(deepcopy(toast))
    proposal=grounded_proposal(case,ctx)
    result=validate_resolution_proposal(proposal,ctx,case)
    assert result.valid_changes and not result.issues
    assert all(a.evidence[-1].ref.get('state_id')=='state-3' for a in proposal.changes[0].expansion)
    stale=deepcopy(ctx);stale.observations['current_state_id']='state-2'
    assert not validate_resolution_proposal(proposal,stale,case).valid_changes
