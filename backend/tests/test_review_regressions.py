import asyncio
import pytest
from test_contract import env, headers, project, task_draft, create_card
from test_agent_and_consistency import ControlledProvider, enable_provider, wait_runs


def test_actual_progress_not_blocked_by_existing_capacity_risk(env):
    c=env[0]
    p=project(env)
    member=c.get('/api/auth/me',headers=headers(env,'member1')).json()['id']
    tasks=c.get(f'/api/projects/{p["id"]}/tasks',headers=headers(env)).json()
    own=next(t for t in tasks if t['assignee_id']==member)
    c.patch(f'/api/projects/{p["id"]}/members/me',headers=headers(env,'member1'),json={'skills':[],'weekly_hours':0})
    response=c.patch(f'/api/tasks/{own["id"]}',headers=headers(env,'member1'),json={'status':'doing','progress':35,'remaining_hours':3,'blocker':'实际阻碍'})
    assert response.status_code==200,response.text
    assert response.json()['progress']==35 and response.json()['blocker']=='实际阻碍'
    assert any(r['code']=='weekly_capacity' for r in response.json()['planning_risks'])
    # 真正改排期时依然硬性校验容量。
    assert c.patch(f'/api/tasks/{own["id"]}',headers=headers(env),json={'title':'规划调整'}).status_code==422


def test_actual_task_update_triggers_adjust_without_chat(env):
    provider=ControlledProvider()
    enable_provider(env,provider)
    c=env[0]
    p=project(env)
    member=c.get('/api/auth/me',headers=headers(env,'member1')).json()['id']
    tasks=c.get(f'/api/projects/{p["id"]}/tasks',headers=headers(env)).json()
    own=next(t for t in tasks if t['assignee_id']==member)
    r=c.patch(f'/api/tasks/{own["id"]}',headers=headers(env,'member1'),json={'progress':20,'status':'doing','remaining_hours':7})
    assert r.status_code==200
    runs=wait_runs(env,'completed')
    assert provider.calls==[[]]
    assert runs[0]['source_message_ids']==[]


def test_current_risks_clear_when_member_capacity_recovers(env):
    c=env[0]
    p=project(env)
    uid=c.get('/api/auth/me',headers=headers(env,'member1')).json()['id']
    tasks=c.get(f'/api/projects/{p["id"]}/tasks',headers=headers(env)).json()
    own=next(t for t in tasks if t['assignee_id']==uid)
    c.patch(f'/api/projects/{p["id"]}/members/me',headers=headers(env,'member1'),json={'skills':[],'weekly_hours':0})
    c.patch(f'/api/tasks/{own["id"]}',headers=headers(env,'member1'),json={'progress':35,'status':'doing','remaining_hours':3})
    risky=c.get(f'/api/projects/{p["id"]}/tasks',headers=headers(env)).json()
    assert next(t for t in risky if t['id']==own['id'])['planning_risks']
    c.patch(f'/api/projects/{p["id"]}/members/me',headers=headers(env,'member1'),json={'skills':[],'weekly_hours':12})
    tasks=c.get(f'/api/projects/{p["id"]}/tasks',headers=headers(env)).json()
    assert next(t for t in tasks if t['id']==own['id'])['planning_risks']==[]
    snapshot=c.get(f'/api/projects/{p["id"]}/progress',headers=headers(env)).json()
    assert snapshot['planning_checks']['valid']
    assert next(t for t in snapshot['tasks'] if t['id']==own['id'])['planning_risks']==[]


def test_students_do_not_receive_old_unpublished_course_history(env):
    c=env[0]
    body={'title':'私有草稿','description':'PRIVATE_DRAFT_TEXT','acceptance_criteria':'验收通过',
          'required_features':['功能'], 'stages':[]}
    created=c.post('/api/courses',headers=headers(env,'teacher'),json=body).json()
    base=c.get('/api/courses',headers=headers(env)).json()[0]
    published=c.patch(f'/api/courses/{created["id"]}',headers=headers(env,'teacher'),
                      json={'status':'published','description':'公开说明','stages':base['stages']})
    assert published.status_code==200
    student=c.get(f'/api/courses/{created["id"]}',headers=headers(env)).json()
    assert 'PRIVATE_DRAFT_TEXT' not in str(student)


@pytest.mark.parametrize('via_card',[True,False])
def test_new_plan_snapshots_use_current_capacity_without_overwriting_history(env,via_card):
    c=env[0]
    p=project(env)
    uid=c.get('/api/auth/me',headers=headers(env,'member1')).json()['id']
    tasks=c.get(f'/api/projects/{p["id"]}/tasks',headers=headers(env)).json()
    own=next(t for t in tasks if t['assignee_id']==uid)
    other=next(t for t in tasks if t['assignee_id']!=uid)
    history=c.get(f'/api/projects/{p["id"]}/plans',headers=headers(env)).json()
    c.patch(f'/api/projects/{p["id"]}/members/me',headers=headers(env,'member1'),json={'skills':[],'weekly_hours':0})
    c.patch(f'/api/tasks/{own["id"]}',headers=headers(env,'member1'),json={'progress':35,'status':'doing','remaining_hours':3})
    c.patch(f'/api/projects/{p["id"]}/members/me',headers=headers(env,'member1'),json={'skills':[],'weekly_hours':12})
    if via_card:
        card=create_card(env,[task_draft(env,title='容量恢复后发布')])
        assert card['checks']['valid']
        published=c.post(f'/api/cards/{card["id"]}/publish',headers=headers(env)).json()
    else:
        response=c.patch(f'/api/tasks/{other["id"]}',headers=headers(env),json={'description':'容量恢复后的人工计划'})
        assert response.status_code==200
        published=c.get(f'/api/projects/{p["id"]}/plans',headers=headers(env)).json()[-1]
    assert all(t['planning_risks']==[] for t in published['tasks'])
    assert all(not change.get('after',{}).get('planning_risks') and not (change.get('before') or {}).get('planning_risks') for change in published['changes'])
    assert c.get(f'/api/projects/{p["id"]}/plans',headers=headers(env)).json()[0]==history[0]


def test_course_acceptance_criteria_persisted_and_required_for_publish(env):
    c=env[0]
    course=c.get('/api/courses',headers=headers(env,'teacher')).json()[0]
    assert course.get('acceptance_criteria'),'教师课程缺少验收标准'
    r=c.patch(f'/api/courses/{course["id"]}',headers=headers(env,'teacher'),json={'acceptance_criteria':'权限、功能、测试和报告全部通过'})
    assert r.status_code==200 and r.json()['acceptance_criteria']=='权限、功能、测试和报告全部通过'
    assert c.patch(f'/api/courses/{course["id"]}',headers=headers(env,'teacher'),json={'acceptance_criteria':''}).status_code==422


class DelayedCorrection(ControlledProvider):
    def __init__(self,card_id):
        super().__init__()
        self.card_id=card_id
    async def analyze(self,context,tools,mode,messages):
        await asyncio.sleep(0.2)
        return {'kind':'discussion','title':'旧分析','summary':'根据旧卡提出调整','questions':['旧分析提出问题'],
                'source_message_ids':[m['id'] for m in messages],'tasks':[],'supersedes_card_ids':[self.card_id]}


def test_old_revision_cannot_supersede_rechecked_card(env):
    c=env[0]
    p=project(env)
    card=create_card(env,[task_draft(env)])
    enable_provider(env,DelayedCorrection(card['id']))
    c.post(f'/api/projects/{p["id"]}/messages',headers=headers(env),json={'content':'讨论更正','client_id':'revision-race'})
    wait_runs(env,'running')
    c.patch(f'/api/projects/{p["id"]}/members/me',headers=headers(env),json={'skills':['Python'],'weekly_hours':12})
    checked=c.patch(f'/api/cards/{card["id"]}',headers=headers(env),json={'reason':'已经根据新容量复核'}).json()
    assert checked['status']=='ready'
    wait_runs(env,'completed')
    cards=c.get(f'/api/projects/{p["id"]}/cards',headers=headers(env)).json()
    assert next(x for x in cards if x['id']==card['id'])['status']=='ready'


def test_same_revision_card_edit_protected_by_snapshot_fingerprint(env):
    c=env[0]
    p=project(env)
    card=create_card(env,[task_draft(env)])
    enable_provider(env,DelayedCorrection(card['id']))
    c.post(f'/api/projects/{p["id"]}/messages',headers=headers(env),json={'content':'讨论','client_id':'card-race'})
    wait_runs(env,'running')
    c.patch(f'/api/cards/{card["id"]}',headers=headers(env),json={'summary':'成员已修订的最新卡片'})
    assert project(env)['revision']==p['revision']
    wait_runs(env,'completed')
    cards=c.get(f'/api/projects/{p["id"]}/cards',headers=headers(env)).json()
    latest=next(x for x in cards if x['id']==card['id'])
    assert latest['status']=='ready' and latest['summary']=='成员已修订的最新卡片'
    assert not any(f.get('kind')=='correction' for f in latest['feedback'])
