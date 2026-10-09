"""Offline audit evaluator; unknown semantics are never silently correct."""
from qctool.generation_evaluation import evaluate_generation


def artifact():
    case={'id':'TC_A_001','obligation_ids':['AC:then'],'generation_status':'ready',
          'steps':[{'action':'assert.url_matches','args':{'pattern':'/a$'}}]}
    return {'cases':[case],'executable_cases':[case],'generated_cases':[case],
        'coverage':{'requirements':[{'obligations':[{'id':'AC:then','status':'covered'}]}]},
        'agent_history':[],'status':'SUCCESS'}


def test_unknown_is_unknown_no_false_pass():
    metrics=evaluate_generation(artifact()).summary()
    assert metrics['semantic']=={'unknown':1}
    assert metrics['unsafe_applied_repairs'] is None
    assert metrics['false_fail_rate'] is None
    assert metrics['runtime_results']=={'Not Executed':1}


def test_reviewed_oracle_incorrect_repair_reported():
    labels={'AC:then':{'steps':[{'action':'assert.url_matches','args':{'pattern':'/b$'}}]}}
    report=evaluate_generation(artifact(),execution={'cases':[{'case_id':'TC_A_001','status':'Fail'}]},ground_truth=labels)
    assert report.summary()['unsafe_applied_repairs']==1
    assert report.summary()['false_fail_rate']==1


def test_expected_abstention_correct():
    gen=artifact();gen['executable_cases']=[]
    assert evaluate_generation(gen,ground_truth={'AC:then':{'expected_abstention':True}}).summary()['semantic']=={'correct':1}
