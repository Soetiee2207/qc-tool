"""Recorded LLM tool replies for a declared route — never a live model claim."""
import json


class RouteReplay:
    """Recorded tool fixture for a declared route. Never a live model claim."""
    def __init__(self, route):
        self.route = route
    def chat(self, messages, tools, **kwargs):
        if tools[0]['function']['name'] == 'design_tests':
            intents = json.loads(messages[-1]['content'])
            name, args = 'design_tests', {'intents':[{'id':i['id'], 'title':i['title'], 'source_quote':i['expected']} for i in intents]}
        else:
            intent = json.loads(messages[1]['content'])['intent']
            if intent['expected'] != 'URL ' + self.route:
                return {'role':'assistant','content':'No recorded safe draft for this source','tool_calls':[]}
            name, args = 'draft_case', {'title':'Declared route', 'steps':[
                {'seq':1,'kind':'given','action':'ui.session','args':{'mode':'anonymous'}},
                {'seq':2,'kind':'when','action':'ui.goto','args':{'url':self.route}},
                {'seq':3,'kind':'then','action':'assert.url_matches','args':{'pattern':self.route+'$'},
                 'source':{'req_id':intent['req_id'],'quote':intent['expected']}}]}
        return {'role':'assistant','content':None,'tool_calls':[{'id':name,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}
