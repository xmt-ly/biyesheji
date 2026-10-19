import asyncio
import time
from threading import Event
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from test_contract import env, headers, project, task_draft, create_card


class ControlledProvider:
    def __init__(self,fail=False,invalid=False,delay=0):
        self.fail,self.invalid,self.delay=fail,invalid,delay
        self.calls=[]
        self.closed=False

    async def analyze(self,context,tools,mode,messages):
        self.calls.append([m['id'] for m in messages])
        assert context['project']['id']==tools.project_id
        with pytest.raises(ValueError):
            tools.execute('get_tasks',{'project_id':999})
        tasks=tools.execute('get_tasks',{})
        assert all(t['existing_id'] is not None for t in tasks)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError('provider credential SECRET_DO_NOT_LEAK')
        return {'kind':'discussion','title':'测试模型的结构化分析','summary':'需要补充估时',
                'questions':['请说明本项工作需要几小时？'],'tasks':[],
                'source_message_ids':[999999] if self.invalid else [m['id'] for m in messages],
                'supersedes_card_ids':[]}

    async def close(self):
        self.closed=True


def enable_provider(env,provider):
    env[2].state.agent.provider=provider
    env[2].state.agent.ready=True


def wait_runs(env,status,count=1):
    p=project(env)
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        runs=env[0].get(f'/api/projects/{p["id"]}/agent/runs',headers=headers(env)).json()
        if len([r for r in runs if r['status']==status])>=count:
            return runs
        time.sleep(0.02)
    pytest.fail(f'未观察到 {count} 次 {status} 分析；最后状态 {runs}')


def test_explicit_agent_request_queues_in_event_loop(env):
    provider=ControlledProvider()
    enable_provider(env,provider)
    p=project(env)
    result=env[0].post(f'/api/projects/{p["id"]}/agent/analyze',headers=headers(env),json={'mode':'plan'})
    assert result.status_code==202
    wait_runs(env,'completed')


def test_agent_failure_is_sanitized_and_chat_stays_available(env):
    enable_provider(env,ControlledProvider(fail=True))
    p=project(env)
    c=env[0]
    assert c.post(f'/api/projects/{p["id"]}/messages',headers=headers(env),json={'content':'讨论','client_id':'failure'}).status_code==200
    runs=wait_runs(env,'failed')
    assert 'SECRET_DO_NOT_LEAK' not in str(runs)
    assert c.post(f'/api/projects/{p["id"]}/messages',headers=headers(env),json={'content':'失败之后继续','client_id':'after-failure'}).status_code==200
    assert c.get(f'/api/projects/{p["id"]}/messages',headers=headers(env)).status_code==200


def test_agent_invalid_source_does_not_advance_cursor(env):
    from app.models import Project
    enable_provider(env,ControlledProvider(invalid=True))
    p=project(env)
    env[0].post(f'/api/projects/{p["id"]}/messages',headers=headers(env),json={'content':'讨论','client_id':'invalid-source'})
    wait_runs(env,'failed')
    with env[2].state.db.Session() as db:
        assert db.get(Project,p['id']).analyzed_message_id==0
    cards=env[0].get(f'/api/projects/{p["id"]}/cards',headers=headers(env)).json()
    assert all(c['status']=='failed' for c in cards)


def test_new_messages_during_analysis_continue_and_duplicate_question_not_repeated(env):
    provider=ControlledProvider(delay=0.1)
    enable_provider(env,provider)
    p=project(env)
    c=env[0]
    c.post(f'/api/projects/{p["id"]}/messages',headers=headers(env),json={'content':'开始讨论','client_id':'first'})
    wait_runs(env,'running')
    c.post(f'/api/projects/{p["id"]}/messages',headers=headers(env),json={'content':'补充内容','client_id':'second'})
    wait_runs(env,'completed',2)
    assert len(provider.calls)==2
    assert provider.calls[0]!=provider.calls[1]
    cards=c.get(f'/api/projects/{p["id"]}/cards',headers=headers(env)).json()
    assert sum(bool(card['questions']) for card in cards)==1


def test_worker_max_window_continuous_input(env):
    provider=ControlledProvider()
    enable_provider(env,provider)
    env[2].state.settings.agent_quiet_seconds=0.2
    env[2].state.settings.agent_max_seconds=0.08
    p=project(env)
    start=time.monotonic()
    for i in range(12):
        env[0].post(f'/api/projects/{p["id"]}/messages',headers=headers(env),json={'content':f'连续{i}','client_id':f'continuous{i}'})
        time.sleep(0.015)
    assert provider.calls,'持续输入必须在最大窗口内开始分析'
    wait_runs(env,'completed')


def test_card_edit_clears_previous_confirmation(env):
    c=env[0]
    card=create_card(env,[task_draft(env,title='初稿')])
    c.post(f'/api/cards/{card["id"]}/feedback',headers=headers(env,'member1'),json={'content':'确认','confirmed':True})
    updated=c.patch(f'/api/cards/{card["id"]}',headers=headers(env),json={'summary':'修改后的草案'}).json()
    assert not any(f['confirmed'] for f in updated['feedback'])


def test_null_patches_and_nonfinite_hours_return_validation_error(env):
    c=env[0]
    p=project(env)
    task=task_draft(env)
    for url,body in [(f'/api/tasks/{task["existing_id"]}',{'assignee_id':None}),
                     (f'/api/projects/{p["id"]}',{'name':None}),
                     (f'/api/courses/{p["course_id"]}',{'title':None})]:
        assert c.patch(url,headers=headers(env,'teacher' if '/courses/' in url else 'leader'),json=body).status_code==422
    result=c.patch(f'/api/tasks/{task["existing_id"]}',headers={**headers(env),'Content-Type':'application/json'},content='{"remaining_hours":NaN}')
    assert result.status_code==422


def test_publish_rollback_keeps_tasks_and_revision(env):
    c,_,app=env
    p=project(env)
    card=create_card(env,[task_draft(env,title='事务中途失败')])
    before=c.get(f'/api/projects/{p["id"]}/tasks',headers=headers(env)).json()
    revision=project(env)['revision']
    def fail_insert(conn,cursor,statement,parameters,context,executemany):
        if statement.startswith('INSERT INTO plans'):
            raise RuntimeError('模拟数据库持久化失败')
    event.listen(app.state.db.engine,'before_cursor_execute',fail_insert)
    try:
        with pytest.raises(RuntimeError):
            c.post(f'/api/cards/{card["id"]}/publish',headers=headers(env))
    finally:
        event.remove(app.state.db.engine,'before_cursor_execute',fail_insert)
    assert project(env)['revision']==revision
    assert c.get(f'/api/projects/{p["id"]}/tasks',headers=headers(env)).json()==before
    assert c.post(f'/api/cards/{card["id"]}/publish',headers=headers(env)).status_code==200


def test_completed_tasks_and_unmentioned_tasks_preserved(env):
    c=env[0]
    p=project(env)
    task=task_draft(env)
    c.patch(f'/api/tasks/{task["existing_id"]}',headers=headers(env),json={'status':'done'})
    card=create_card(env,[dict(task,title='模型试图修改完成任务')])
    assert any(v['code']=='completed_task' for v in card['checks']['violations'])
    assert c.post(f'/api/cards/{card["id"]}/publish',headers=headers(env)).status_code==422


def test_cross_project_references_and_correction_sources(env):
    c=env[0]
    p=project(env)
    outside=project(env,'leader2')
    foreign=c.get(f'/api/projects/{outside["id"]}/tasks',headers=headers(env,'leader2')).json()[0]
    assert c.post(f'/api/projects/{p["id"]}/messages',headers=headers(env),json={'content':'越权引用','client_id':'foreign','related_type':'task','related_id':foreign['id']}).status_code==422
    foreign_message=c.post(f'/api/projects/{outside["id"]}/messages',headers=headers(env,'leader2'),json={'content':'另一团队私有信息','client_id':'outside'}).json()
    assert c.post(f'/api/projects/{p["id"]}/cards',headers=headers(env),json={'kind':'discussion','summary':'跨项目引用','source_message_ids':[foreign_message['id']]}).status_code==422
    card=create_card(env,[task_draft(env)])
    assert c.post(f'/api/projects/{p["id"]}/messages',headers=headers(env),json={'content':'更正旧建议','client_id':'correction','supersedes_card_ids':[card['id']]}).status_code==200
    assert c.post(f'/api/cards/{card["id"]}/publish',headers=headers(env)).status_code==409
