import asyncio
import json
import time
from types import SimpleNamespace
from fastapi.testclient import TestClient
from sqlalchemy import select
import pytest
from test_contract import env, headers, project, task_draft, create_card
from test_agent_and_consistency import ControlledProvider, enable_provider, wait_runs


def test_teacher_plan_summary_cannot_copy_internal_card(env):
    c=env[0]
    p=project(env)
    card=create_card(env,[task_draft(env,title='公开任务修改')])
    c.patch(f'/api/cards/{card["id"]}',headers=headers(env),json={'summary':'INTERNAL_PRIVATE_CARD_SUMMARY'})
    assert c.post(f'/api/cards/{card["id"]}/publish',headers=headers(env)).status_code==200
    plans=c.get(f'/api/projects/{p["id"]}/plans',headers=headers(env,'teacher')).json()
    assert 'INTERNAL_PRIVATE_CARD_SUMMARY' not in json.dumps(plans)


def test_other_teacher_cannot_access_course_project_or_review(env):
    from app.models import User
    from app.security import hash_password
    c,_,app=env
    with app.state.db.Session() as db:
        db.add(User(username='teacher2',name='其他教师',identity='teacher',password_hash=hash_password('Demo2026!')))
        db.commit()
    token=c.post('/api/auth/login',json={'username':'teacher2','password':'Demo2026!'}).json()['access_token']
    h={'Authorization':'Bearer '+token}
    p=project(env)
    sub=c.post(f'/api/projects/{p["id"]}/submissions',headers=headers(env),json={'stage_index':0,'summary':'材料','artifact_urls':['https://example.com'],'file_ids':[]}).json()
    assert c.get(f'/api/courses/{p["course_id"]}',headers=h).status_code==403
    assert c.get(f'/api/projects/{p["id"]}',headers=h).status_code==403
    assert c.post(f'/api/submissions/{sub["id"]}/review',headers=h,json={'result':'passed','comment':'非法审核'}).status_code==403


def test_course_revision_invalidates_cards(env):
    c=env[0]
    p=project(env)
    card=create_card(env,[task_draft(env)])
    c.patch(f'/api/courses/{p["course_id"]}',headers=headers(env,'teacher'),json={'description':'教师调整课程要求'})
    assert project(env)['revision']>p['revision']
    assert c.post(f'/api/cards/{card["id"]}/publish',headers=headers(env)).status_code==409


def test_slow_model_output_becomes_stale_when_task_changes(env):
    from app.schemas import AgentOutput
    class PlanProvider(ControlledProvider):
        async def analyze(self,context,tools,mode,messages):
            await asyncio.sleep(0.2)
            return {'kind':'plan','title':'模型草案','summary':'根据旧状态规划','questions':[],
                    'source_message_ids':[m['id'] for m in messages],'tasks':[dict(context['tasks'][0],title='旧状态建议')],'supersedes_card_ids':[]}
    enable_provider(env,PlanProvider())
    c=env[0]
    p=project(env)
    c.post(f'/api/projects/{p["id"]}/messages',headers=headers(env),json={'content':'规划任务','client_id':'slow'})
    wait_runs(env,'running')
    t=task_draft(env)
    c.patch(f'/api/tasks/{t["existing_id"]}',headers=headers(env),json={'progress':25,'status':'doing'})
    wait_runs(env,'completed')
    cards=c.get(f'/api/projects/{p["id"]}/cards',headers=headers(env)).json()
    assert cards[-1]['status']=='stale'
    assert c.post(f'/api/cards/{cards[-1]["id"]}/publish',headers=headers(env)).status_code==409
    tasks=c.get(f'/api/projects/{p["id"]}/tasks',headers=headers(env)).json()
    assert tasks[0]['progress']==25


def test_model_correction_and_cross_project_tool_context(env):
    c,_,app=env
    p=project(env)
    old=create_card(env,[task_draft(env)])
    other=project(env,'leader2')
    c.post(f'/api/projects/{other["id"]}/messages',headers=headers(env,'leader2'),json={'content':'FOREIGN_SECRET','client_id':'secret'})
    class CorrectionProvider(ControlledProvider):
        async def analyze(self,context,tools,mode,messages):
            assert 'FOREIGN_SECRET' not in json.dumps(context,ensure_ascii=False)
            assert all(t['existing_id'] in [1,2] for t in context['tasks'])
            return {'kind':'discussion','title':'更正','summary':'新信息更正旧分工','questions':['请核对新的时间'],
                    'source_message_ids':[m['id'] for m in messages],'tasks':[],'supersedes_card_ids':[old['id']]}
    enable_provider(env,CorrectionProvider())
    c.post(f'/api/projects/{p["id"]}/messages',headers=headers(env),json={'content':'更正旧分工','client_id':'correct'})
    wait_runs(env,'completed')
    cards=c.get(f'/api/projects/{p["id"]}/cards',headers=headers(env)).json()
    assert cards[0]['status']=='stale'
    assert cards[-1]['supersedes_card_ids']==[old['id']]
    assert any(f.get('superseded_by_card_id')==cards[-1]['id'] for f in cards[0]['feedback'])


def test_message_correction_provenance_is_persisted(env):
    c=env[0]
    p=project(env)
    card=create_card(env,[task_draft(env)])
    sent=c.post(f'/api/projects/{p["id"]}/messages',headers=headers(env),json={'content':'明确更正','client_id':'persist-correction','supersedes_card_ids':[card['id']]}).json()
    history=c.get(f'/api/projects/{p["id"]}/messages',headers=headers(env)).json()
    assert history[-1]['supersedes_card_ids']==[card['id']]
    cards=c.get(f'/api/projects/{p["id"]}/cards',headers=headers(env)).json()
    assert any(f.get('source_message_id')==sent['id'] for f in cards[0]['feedback'])


def test_new_task_key_mapping_and_full_snapshot(env):
    c=env[0]
    p=project(env)
    base=task_draft(env)
    # 排在下一周，避免与现有任务占用同周容量。
    from datetime import date,timedelta
    start=date.fromisoformat(base['due_date'])+timedelta(days=3)
    new=dict(base,key='new_followup',existing_id=None,title='后续任务',start_date=start.isoformat(),
             due_date=(start+timedelta(days=2)).isoformat(),dependencies=[base['key']],stage_index=2,remaining_hours=2,estimated_hours=2)
    card=create_card(env,[new])
    assert card['checks']['valid'],card['checks']
    plan=c.post(f'/api/cards/{card["id"]}/publish',headers=headers(env)).json()
    assert len(plan['tasks'])==3
    inserted=next(t for t in plan['tasks'] if t['title']=='后续任务')
    assert inserted['dependencies']==[base['existing_id']]


def test_sdk_provider_uses_tools_and_aggregates_usage():
    from app.agent import OpenAIProvider
    from app.config import Settings
    class Message:
        def __init__(self,calls=None,content=None):
            self.tool_calls=calls
            self.content=content
        def model_dump(self,**kwargs):
            return {'role':'assistant','tool_calls':[{'id':'call1','type':'function','function':{'name':'get_tasks','arguments':'{}'}}]}
    class Chat:
        def __init__(self):
            self.requests=[]
        async def create(self,**kwargs):
            self.requests.append(kwargs)
            message=Message(calls=[SimpleNamespace(id='call1',function=SimpleNamespace(name='get_tasks',arguments='{}'))]) if len(self.requests)==1 else Message(content=json.dumps({'kind':'discussion','title':'分析','summary':'无需变更','tasks':[],'questions':[],'source_message_ids':[]}))
            return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10,completion_tokens=5,total_tokens=15),choices=[SimpleNamespace(message=message)])
    class Tools:
        def __init__(self):self.calls=[]
        def execute(self,name,args):self.calls.append((name,args));return []
    chat=Chat()
    provider=OpenAIProvider(Settings(llm_api_key='',llm_model='test-model'))
    provider.client=SimpleNamespace(chat=SimpleNamespace(completions=chat))
    tools=Tools()
    result=asyncio.run(provider.analyze({},tools,'discussion',[]))
    assert tools.calls==[('get_tasks',{}),('check_plan',{'tasks':[]})]
    assert result['tokens']['total_tokens']==30
    assert chat.requests[1]['messages'][-1]['role']=='tool'
    assert chat.requests[0]['model']=='test-model'
    from app.schemas import AgentOutput
    assert AgentOutput.model_validate(result['output']).kind=='discussion'


def test_sdk_provider_corrects_plan_after_tool_feedback_without_json_tool_conflict(env):
    from app.agent import OpenAIProvider, ProjectTools
    from app.config import Settings
    from app.schemas import AgentOutput
    p=project(env)
    base=task_draft(env)
    bad=dict(base,key='task_new',existing_id=None,title='新增回归测试',estimated_hours=1,remaining_hours=1,status='todo',progress=0)
    good=dict(bad,key='new_regression')
    assignee=next(m['name'] for m in p['members'] if m['user_id']==good['assignee_id'])
    quote=f"{assignee}负责新增回归测试，预计1小时，{good['start_date']}开始，{good['due_date']}截止。"
    source=env[0].post(f'/api/projects/{p["id"]}/messages',headers=headers(env),
                       json={'content':quote,'client_id':'sdk-grounded-regression'}).json()
    class Message:
        def __init__(self,calls=None,content=None):self.tool_calls=calls;self.content=content
        def model_dump(self,**kwargs):
            return {'role':'assistant','tool_calls':[{'id':call.id,'type':'function','function':{'name':call.function.name,'arguments':call.function.arguments}} for call in self.tool_calls]}
    class Chat:
        def __init__(self):self.requests=[]
        async def create(self,**kwargs):
            self.requests.append(kwargs)
            if kwargs.get('tools') and kwargs.get('response_format'):
                message=Message(content='{"":""}')  # 实测端点的工具/JSON格式冲突结果。
            else:
                step=len(self.requests)
                if step in (1,2):
                    name='get_tasks' if step==1 else 'get_project_context'; arguments={}
                elif step in (3,4):
                    feedback=json.loads(kwargs['messages'][-1]['content'])
                    if step==4:
                        assert not feedback['valid'] and any(v['code']=='reserved_key' for v in feedback['violations'])
                    name='check_plan'; arguments={'tasks':[bad if step==3 else good]}
                else:
                    assert json.loads(kwargs['messages'][-1]['content'])['valid']
                    name='finalize_analysis'
                    arguments={'analysis':{'kind':'plan','title':'校验后的草案','summary':'根据真实工具反馈修正标识',
                            'questions':[],'source_message_ids':[source['id']],'tasks':[good],'supersedes_card_ids':[]},
                            'task_evidence':[{'task_key':good['key'],'field':field,'message_id':source['id'],'quote':quote}
                                             for field in ['assignee_id','estimated_hours','start_date','due_date']]}
                    message=Message(calls=[SimpleNamespace(id='finalize',function=SimpleNamespace(name=name,arguments=json.dumps(arguments)))])
                if step<=4:
                    message=Message(calls=[SimpleNamespace(id=f'call{step}',function=SimpleNamespace(name=name,arguments=json.dumps(arguments)))])
            return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10,completion_tokens=5,total_tokens=15),choices=[SimpleNamespace(message=message)])
    chat=Chat()
    provider=OpenAIProvider(Settings(llm_api_key='',llm_model='test-model'))
    provider.client=SimpleNamespace(chat=SimpleNamespace(completions=chat))
    tools=ProjectTools(env[2].state.db,p['id'])
    result=asyncio.run(provider.analyze({},tools,'plan',[source]))
    output=AgentOutput.model_validate(result['output'])
    assert output.tasks[0].key=='new_regression'
    assert [item['name'] for item in tools.results]==['get_tasks','get_project_context','check_plan','check_plan']
    assert tools.results[-1]['result']['valid']
    assert result['tokens']['total_tokens']==75


def test_restart_recovers_unanalyzed_messages_and_closes_provider(env,tmp_path):
    from app.main import create_app
    from app.config import Settings
    c,_,app=env
    p=project(env)
    c.post(f'/api/projects/{p["id"]}/messages',headers=headers(env),json={'content':'重启前未分析消息','client_id':'restart'})
    provider=ControlledProvider()
    settings=Settings(database_url=app.state.settings.database_url,data_dir=app.state.settings.data_dir,
                      jwt_secret=app.state.settings.jwt_secret,agent_quiet_seconds=0.01,agent_max_seconds=0.02)
    restarted=create_app(settings,provider)
    with TestClient(restarted) as second:
        deadline=time.monotonic()+2
        while not provider.calls and time.monotonic()<deadline:
            time.sleep(0.01)
        assert provider.calls
        response=second.get(f'/api/projects/{p["id"]}/messages',headers=headers(env))
        assert response.status_code==200
    assert provider.closed
