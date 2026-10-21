"""OpenAI-compatible tool transport; no live network."""
import json
from unittest.mock import MagicMock,Mock
from urllib.error import URLError
import pytest
from qctool.agent.llm_provider import OpenAICompatibleLLM,LLMProviderError,capture_provider_attempts


def http(monkeypatch,payload):
    import qctool.agent.llm_provider as p
    response=MagicMock();response.status=200;response.__enter__.return_value=response
    response.read.return_value=json.dumps(payload).encode()
    opener=Mock();opener.open.return_value=response
    monkeypatch.setattr(p.request,'build_opener',lambda *_:opener)
    return opener


def test_tool_envelope_without_content_and_usage(monkeypatch):
    payload={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','tool_calls':[
        {'id':'a','type':'function','function':{'name':'read_docs','arguments':'{}'}}]}}],
        'usage':{'prompt_tokens':100,'completion_tokens':5,'total_tokens':105,'prompt_cache_hit_tokens':80,'prompt_cache_miss_tokens':20}}
    opener=http(monkeypatch,payload)
    with capture_provider_attempts() as records:
        result=OpenAICompatibleLLM('https://provider.test','model','SECRET').chat([{'role':'user','content':'Docs'}],[])
    assert result['tool_calls'][0]['function']['name']=='read_docs'
    sent=json.loads(opener.open.call_args.args[0].data)
    assert 'response_format' not in sent and sent['tool_choice']=='auto'
    assert records[0]['cache_usage']['hit_ratio']==0.8
    assert 'Docs' not in json.dumps(records) and 'SECRET' not in json.dumps(records)


def test_chat_retries_transient_timeout_exactly_once(monkeypatch):
    # One slow reply must not discard a whole authoring session; never more than one retry.
    import qctool.agent.llm_provider as p
    opener=Mock();opener.open.side_effect=URLError(TimeoutError('SECRET'))
    monkeypatch.setattr(p.request,'build_opener',lambda *_:opener)
    with capture_provider_attempts() as records, pytest.raises(LLMProviderError):
        OpenAICompatibleLLM('https://provider.test','model','SECRET').chat([{'role':'user','content':'Docs'}],[])
    assert opener.open.call_count==2
    assert [r['retry_scheduled'] for r in records]==[True,False]
    assert 'SECRET' not in json.dumps(records)


def test_tool_history_is_forwarded_and_reasoning_not_audited(monkeypatch):
    opener=http(monkeypatch,{'choices':[{'message':{'content':None,'reasoning_content':'private reasoning',
        'tool_calls':[{'id':'b','type':'function','function':{'name':'read_docs','arguments':'{}'}}]},'finish_reason':'tool_calls'}]})
    messages=[{'role':'assistant','content':None,'reasoning_content':'prior reasoning','tool_calls':[
        {'id':'a','type':'function','function':{'name':'read_docs','arguments':'{}'}}]}, {'role':'tool','tool_call_id':'a','content':'{}'}]
    with capture_provider_attempts() as records:
        result=OpenAICompatibleLLM('https://provider.test','model','SECRET').chat(messages,[])
    assert json.loads(opener.open.call_args.args[0].data)['messages']==messages
    assert result['reasoning_content']=='private reasoning'
    assert 'reasoning' not in json.dumps(records)


def test_thinking_is_explicit_optional_provider_config(monkeypatch):
    payload={'choices':[{'message':{'content':None,'tool_calls':[
        {'id':'a','type':'function','function':{'name':'read_docs','arguments':'{}'}}]},'finish_reason':'tool_calls'}]}
    opener=http(monkeypatch,payload)
    OpenAICompatibleLLM('https://provider.test','model','SECRET',thinking='disabled').chat([{'role':'user','content':'Docs'}],[])
    assert json.loads(opener.open.call_args.args[0].data)['thinking']=={'type':'disabled'}
