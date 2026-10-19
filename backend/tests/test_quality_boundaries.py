import asyncio
import time
from datetime import datetime, timedelta, timezone
from concurrent.futures import CancelledError as FutureCancelledError
import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_contract import env, headers, project, task_draft, create_card
from test_agent_and_consistency import ControlledProvider, enable_provider, wait_runs


@pytest.mark.parametrize('initial_status',['published','archived'])
def test_once_public_course_cannot_return_to_private_draft_atomically(env,initial_status):
    from app.agent import ProjectTools
    c,_,app=env
    p=project(env)
    if initial_status=='archived':
        c.patch(f'/api/courses/{p["course_id"]}',headers=headers(env,'teacher'),json={'status':'archived'})
    before=c.get(f'/api/courses/{p["course_id"]}',headers=headers(env,'teacher')).json()
    response=c.patch(f'/api/courses/{p["course_id"]}',headers=headers(env,'teacher'),
                     json={'status':'draft','description':'PRIVATE_AFTER_WITHDRAW','required_features':['私有修改']})
    assert response.status_code==409,response.text
    assert c.get(f'/api/courses/{p["course_id"]}',headers=headers(env,'teacher')).json()==before
    assert 'PRIVATE_AFTER_WITHDRAW' not in str(ProjectTools(app.state.db,p['id']).execute('get_project_context',{}))


def test_legacy_project_attached_to_draft_cannot_expose_private_course(env):
    from app.agent import ProjectTools
    from app.models import Course,Project
    from app.planning import check_plan
    c,_,app=env
    p=project(env)
    with app.state.db.Session() as db:
        course=db.get(Course,p['course_id'])
        course.status='draft'
        course.description='LEGACY_PRIVATE_DRAFT'
        db.commit()
    response=c.get(f'/api/projects/{p["id"]}/progress',headers=headers(env))
    assert response.status_code==403 and 'LEGACY_PRIVATE_DRAFT' not in response.text
    with pytest.raises(HTTPException) as error:
        ProjectTools(app.state.db,p['id']).execute('get_project_context',{})
    assert error.value.status_code==403
    with app.state.db.Session() as db:
        with pytest.raises(HTTPException):
            check_plan(db,db.get(Project,p['id']),[])


class ModeRecorder(ControlledProvider):
    def __init__(self,delay=0,fail=False):
        super().__init__(delay=delay,fail=fail)
        self.modes=[]
        self.contexts=[]
    async def analyze(self,context,tools,mode,messages):
        self.modes.append(mode)
        self.contexts.append(context)
        return await super().analyze(context,tools,mode,messages)


def restart(env,provider):
    from app.config import Settings
    from app.main import create_app
    app=env[2]
    settings=Settings(database_url=app.state.settings.database_url,data_dir=app.state.settings.data_dir,
                      jwt_secret=app.state.settings.jwt_secret,agent_quiet_seconds=0.01,agent_max_seconds=0.02)
    return create_app(settings,provider)


def wait_calls(provider,count=1):
    deadline=time.monotonic()+3
    while len(provider.modes)<count and time.monotonic()<deadline:
        time.sleep(0.01)
    assert len(provider.modes)>=count,'重启后丢失了无聊天消息的分析意图'


def test_quiet_queued_plan_without_chat_survives_shutdown(env):
    c,_,app=env
    old=ModeRecorder()
    enable_provider(env,old)
    app.state.settings.agent_quiet_seconds=5
    app.state.settings.agent_max_seconds=5
    p=project(env)
    assert c.post(f'/api/projects/{p["id"]}/agent/analyze',headers=headers(env),json={'mode':'plan'}).status_code==202
    c.portal.call(app.state.agent.close)
    assert old.modes==[]
    resumed=ModeRecorder()
    with TestClient(restart(env,resumed)):
        wait_calls(resumed)
        assert resumed.modes==['plan']


def test_running_adjust_and_new_pending_without_chat_survive_shutdown_with_latest_data(env):
    c,_,app=env
    old=ModeRecorder(delay=10)
    enable_provider(env,old)
    p=project(env)
    t=task_draft(env)
    assert c.patch(f'/api/tasks/{t["existing_id"]}',headers=headers(env),json={'status':'doing','progress':20,'remaining_hours':7}).status_code==200
    wait_calls(old)
    assert old.modes==['adjust']
    assert c.patch(f'/api/tasks/{t["existing_id"]}',headers=headers(env),json={'progress':45,'remaining_hours':3}).status_code==200
    c.portal.call(app.state.agent.close)
    resumed=ModeRecorder()
    with TestClient(restart(env,resumed)):
        wait_calls(resumed)
        assert resumed.modes==['adjust']
        assert next(x for x in resumed.contexts[0]['tasks'] if x['existing_id']==t['existing_id'])['progress']==45


def test_failed_agent_intent_not_retried_automatically_on_restart(env):
    c,_,app=env
    old=ModeRecorder(fail=True)
    enable_provider(env,old)
    p=project(env)
    c.post(f'/api/projects/{p["id"]}/messages',headers=headers(env),json={'content':'失败讨论','client_id':'no-auto-retry'})
    wait_runs(env,'failed')
    c.portal.call(app.state.agent.close)
    resumed=ModeRecorder()
    with TestClient(restart(env,resumed)):
        time.sleep(0.12)
        assert resumed.modes==[],'模型失败后重启不能无限自动扣费重试'


def test_completed_analysis_checkpoint_not_reclassified_when_shutdown_interrupts_broadcast(env):
    c,_,app=env
    provider=ModeRecorder()
    enable_provider(env,provider)
    async def block_completed_event(project_id,event):
        if event.get('type')=='agent_status' and event.get('status')=='completed':
            await asyncio.sleep(10)
    app.state.hub.broadcast=block_completed_event
    p=project(env)
    c.post(f'/api/projects/{p["id"]}/agent/analyze',headers=headers(env),json={'mode':'plan'})
    wait_runs(env,'completed')
    c.portal.call(app.state.agent.close)
    runs=c.get(f'/api/projects/{p["id"]}/agent/runs',headers=headers(env)).json()
    assert runs[0]['status']=='completed'


@pytest.mark.parametrize('trigger',['task','message','explicit'])
def test_business_commit_and_agent_intent_share_checkpoint_before_first_postcommit_interrupt(env,trigger):
    from app.models import AgentIntent,Task,Message
    c,_,app=env
    old=ModeRecorder()
    enable_provider(env,old)
    app.state.settings.agent_quiet_seconds=5
    app.state.settings.agent_max_seconds=5
    p=project(env)
    t=task_draft(env)
    async def interrupt_first_broadcast(project_id,event):
        raise asyncio.CancelledError()
    app.state.hub.broadcast=interrupt_first_broadcast
    if trigger=='explicit':
        def interrupt_wake(project_id):
            raise asyncio.CancelledError()
        app.state.agent._wake=interrupt_wake
    try:
        if trigger=='task':
            c.patch(f'/api/tasks/{t["existing_id"]}',headers=headers(env),json={'status':'doing','progress':31,'remaining_hours':3})
        elif trigger=='message':
            c.post(f'/api/projects/{p["id"]}/messages',headers=headers(env),json={'content':'提交后中断仍保留分析意图','client_id':'commit-window'})
        else:
            c.post(f'/api/projects/{p["id"]}/agent/analyze',headers=headers(env),json={'mode':'plan'})
    except (asyncio.CancelledError,FutureCancelledError):
        pass
    c.portal.call(app.state.agent.close)
    with app.state.db.Session() as db:
        if trigger=='task':
            assert db.get(Task,t['existing_id']).progress==31
        elif trigger=='message':
            assert db.scalar(select(Message).where(Message.client_id=='commit-window'))
        intents=db.scalars(select(AgentIntent).where(AgentIntent.project_id==p['id'])).all()
        assert len(intents)==1,'业务提交成功时必须同时保存 Agent 意图，不能依赖之后的广播完成'
        expected={'task':'adjust','message':'discussion','explicit':'plan'}[trigger]
        assert intents[0].mode==expected and intents[0].status=='queued'
    resumed=ModeRecorder()
    with TestClient(restart(env,resumed)):
        wait_calls(resumed)
        assert resumed.modes==[expected]
        if trigger=='task':
            assert next(x for x in resumed.contexts[0]['tasks'] if x['existing_id']==t['existing_id'])['progress']==31


@pytest.mark.parametrize('suffix',['/projects/{id}','/courses/{id}','/files/{id}','/projects/{id}/messages?after_id=0'])
def test_sqlite_oversized_path_id_rejected_before_query(env,suffix):
    assert env[0].get('/api'+suffix.format(id=2**63),headers=headers(env)).status_code==422


def test_oversized_related_source_and_cursor_ids_return_422(env):
    c=env[0]
    p=project(env)
    big=2**63
    assert c.post(f'/api/projects/{p["id"]}/messages',headers=headers(env),json={'content':'引用过大','client_id':'big','related_type':'task','related_id':big}).status_code==422
    assert c.post(f'/api/projects/{p["id"]}/cards',headers=headers(env),json={'summary':'来源过大','source_message_ids':[big]}).status_code==422
    assert c.get(f'/api/projects/{p["id"]}/messages?after_id={big}',headers=headers(env)).status_code==422


def test_oversized_signed_jwt_subject_returns_401(env):
    token=jwt.encode({'sub':str(2**63),'exp':datetime.now(timezone.utc)+timedelta(minutes=5)},env[2].state.settings.jwt_secret,algorithm='HS256')
    assert env[0].get('/api/auth/me',headers={'Authorization':'Bearer '+token}).status_code==401


def test_date_max_task_and_week_end_do_not_overflow(env):
    c=env[0]
    p=project(env)
    stages=[{'name':f'阶段{i}','deadline':d,'deliverables':['材料']} for i,d in enumerate(['9999-12-29','9999-12-30','9999-12-31'])]
    assert c.patch(f'/api/courses/{p["course_id"]}',headers=headers(env,'teacher'),json={'stages':stages}).status_code==200
    card=create_card(env,[task_draft(env,start_date='9999-12-31',due_date='9999-12-31',remaining_hours=100,stage_index=2)])
    assert any(v['code']=='weekly_capacity' for v in card['checks']['violations'])


def test_patch_card_has_same_tasks_and_questions_limits_as_create(env):
    c=env[0]
    card=create_card(env,[task_draft(env)])
    drafts=[task_draft(env,key=f'new_{i}',existing_id=None,remaining_hours=0,estimated_hours=0) for i in range(301)]
    assert c.patch(f'/api/cards/{card["id"]}',headers=headers(env),json={'tasks':drafts}).status_code==422
    assert c.patch(f'/api/cards/{card["id"]}',headers=headers(env),json={'questions':['问题']*101}).status_code==422


def test_existing_1200_dependency_chain_and_cycle_use_iterative_check(env):
    from app.models import Task
    c,_,app=env
    p=project(env)
    base=task_draft(env)
    with app.state.db.Session() as db:
        rows=[Task(project_id=p['id'],creator_id=p['members'][0]['user_id'],title=f'链{i}',description='',
                   requirement_id=base['requirement_id'],acceptance='通过',assignee_id=base['assignee_id'],
                   estimated_hours=0,remaining_hours=0,start_date=base['start_date'],due_date=base['due_date'],
                   status='done',progress=100,stage_index=2) for i in range(1200)]
        db.add_all(rows)
        db.flush()
        for index,row in enumerate(rows[:-1]):
            row.dependencies=[rows[index+1].id]
        last_id,first_id=rows[-1].id,rows[0].id
        db.commit()
    assert c.get(f'/api/projects/{p["id"]}/tasks',headers=headers(env)).status_code==200
    assert c.get(f'/api/projects/{p["id"]}/progress',headers=headers(env)).json()['planning_checks']['valid']
    with app.state.db.Session() as db:
        db.get(Task,last_id).dependencies=[first_id]
        db.commit()
    response=c.get(f'/api/projects/{p["id"]}/progress',headers=headers(env))
    assert response.status_code==200
    assert any(v['code']=='dependency_cycle' for v in response.json()['planning_checks']['violations'])
