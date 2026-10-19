import importlib.util
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def test_application_factory_exists():
    assert importlib.util.find_spec('app.main') is not None, '尚未实现后端应用工厂'


@pytest.fixture
def env(tmp_path):
    from app.main import create_app
    from app.config import Settings
    from app.seed import seed_demo
    app = create_app(Settings(database_url=f'sqlite:///{tmp_path}/test.db', data_dir=tmp_path,
                              jwt_secret='test-secret-long-enough-for-jwt-2026', agent_quiet_seconds=0.03,
                              agent_max_seconds=0.1,llm_api_key='',llm_model=''))
    with TestClient(app) as client:
        seed_demo(app.state.db.Session)
        tokens = {}
        for username in ['teacher', 'leader', 'member1', 'member2', 'leader2', 'member3']:
            response = client.post('/api/auth/login', json={'username': username, 'password': 'Demo2026!'})
            assert response.status_code == 200
            tokens[username] = response.json()['access_token']
        yield client, tokens, app


def headers(env, name='leader'):
    return {'Authorization': f'Bearer {env[1][name]}'}


def project(env, name='leader'):
    return env[0].get('/api/projects', headers=headers(env, name)).json()[0]


def test_login_and_draft_visibility(env):
    c, _, _ = env
    assert c.post('/api/auth/login', json={'username':'leader','password':'wrong'}).status_code == 401
    assert c.get('/api/auth/me', headers=headers(env)).json()['username'] == 'leader'
    assert c.get('/api/projects').status_code == 401
    courses = c.get('/api/courses', headers=headers(env)).json()
    assert all(x['status'] == 'published' for x in courses)
    assert len(c.get('/api/courses', headers=headers(env,'teacher')).json()) > len(courses)


@pytest.mark.parametrize('suffix', ['','/requirements','/tasks','/plans','/submissions','/messages','/cards'])
def test_other_team_cannot_read(env, suffix):
    p = project(env)
    assert env[0].get(f'/api/projects/{p["id"]}{suffix}',headers=headers(env,'member3')).status_code == 403


@pytest.mark.parametrize('suffix', ['/messages','/cards','/agent/runs'])
def test_teacher_cannot_read_internal_data(env, suffix):
    p=project(env)
    assert env[0].get(f'/api/projects/{p["id"]}{suffix}',headers=headers(env,'teacher')).status_code == 403


def test_websocket_scope_and_reconnect(env):
    c,tokens,_=env
    p=project(env)
    for name in ['teacher','member3']:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect(f'/api/projects/{p["id"]}/ws?token={tokens[name]}'):
                pass
    with c.websocket_connect(f'/api/projects/{p["id"]}/ws?token={tokens["member1"]}') as ws:
        payload={'content':'持久化消息','client_id':'unique-client-message'}
        r=c.post(f'/api/projects/{p["id"]}/messages',headers=headers(env),json=payload)
        assert r.status_code == 200
        event=ws.receive_json()
        assert event['type']=='message' and event['message']['id']==r.json()['id']
    repeat=c.post(f'/api/projects/{p["id"]}/messages',headers=headers(env),json=payload)
    assert repeat.json()['id']==r.json()['id']
    history=c.get(f'/api/projects/{p["id"]}/messages?after_id=0',headers=headers(env)).json()
    assert len([m for m in history if m['client_id']=='unique-client-message'])==1


def test_member_can_only_update_own_progress_and_capacity(env):
    c,_,_=env
    p=project(env)
    tasks=c.get(f'/api/projects/{p["id"]}/tasks',headers=headers(env)).json()
    member=c.get('/api/auth/me',headers=headers(env,'member1')).json()['id']
    own=next(t for t in tasks if t['assignee_id']==member)
    other=next(t for t in tasks if t['assignee_id']!=member)
    assert c.patch(f'/api/tasks/{own["id"]}',headers=headers(env,'member1'),json={'progress':35,'status':'doing','remaining_hours':3}).status_code==200
    assert c.patch(f'/api/tasks/{other["id"]}',headers=headers(env,'member1'),json={'progress':35}).status_code==403
    assert c.patch(f'/api/tasks/{own["id"]}',headers=headers(env,'member1'),json={'assignee_id':member}).status_code==403
    assert c.patch(f'/api/projects/{p["id"]}/members/me',headers=headers(env,'member1'),json={'skills':['Python'],'weekly_hours':14}).status_code==200
    assert c.post(f'/api/projects/{p["id"]}/members',headers=headers(env,'member1'),json={'username':'member3'}).status_code==403


def test_project_role_not_global(env):
    c,_,_=env
    p=project(env)
    assert c.post(f'/api/projects/{p["id"]}/members',headers=headers(env),json={'username':'leader2'}).status_code==200
    assert c.post(f'/api/projects/{p["id"]}/members',headers=headers(env,'leader2'),json={'username':'member3'}).status_code==403


def test_requirements_confirmation_permission_and_cross_reference(env):
    c,_,_=env
    p=project(env)
    r=c.post(f'/api/projects/{p["id"]}/requirements',headers=headers(env,'member1'),json={'title':'新需求','description':'说明','acceptance':'测试通过'}).json()
    assert r['status']=='draft'
    assert c.patch(f'/api/requirements/{r["id"]}',headers=headers(env,'member1'),json={'status':'confirmed'}).status_code==403
    assert c.patch(f'/api/requirements/{r["id"]}',headers=headers(env),json={'status':'confirmed'}).status_code==200
    assert c.patch(f'/api/requirements/{r["id"]}',headers=headers(env,'member3'),json={'title':'越权'}).status_code==403


def task_draft(env, **overrides):
    p=project(env)
    task=env[0].get(f'/api/projects/{p["id"]}/tasks',headers=headers(env)).json()[0]
    draft={k:v for k,v in task.items() if k in ['title','description','requirement_id','acceptance','assignee_id','estimated_hours','remaining_hours','start_date','due_date','status','progress','artifact_url','blocker']}
    draft.update(key=task['key'],existing_id=task['id'],dependencies=[])
    draft.update(overrides)
    return draft


def create_card(env,tasks):
    p=project(env)
    r=env[0].post(f'/api/projects/{p["id"]}/cards',headers=headers(env),json={'kind':'plan','title':'人工规划草案','summary':'人工核对','tasks':tasks})
    assert r.status_code==200,r.text
    return r.json()


def test_plan_checks_overlay_cycle_dates_capacity_and_cross_team(env):
    c,_,_=env
    p=project(env)
    t=task_draft(env)
    card=create_card(env,[dict(t,dependencies=[t['key']])])
    assert 'dependency_cycle' in [v['code'] for v in card['checks']['violations']]
    card=create_card(env,[dict(t,start_date='2030-01-02',due_date='2030-01-01')])
    assert 'date_order' in [v['code'] for v in card['checks']['violations']]
    card=create_card(env,[dict(t,remaining_hours=1000)])
    assert 'weekly_capacity' in [v['code'] for v in card['checks']['violations']]
    outside=project(env,'leader2')['members'][0]['user_id']
    card=create_card(env,[dict(t,assignee_id=outside)])
    assert 'invalid_assignee' in [v['code'] for v in card['checks']['violations']]
    assert c.post(f'/api/cards/{card["id"]}/publish',headers=headers(env)).status_code==422


def test_card_staleness_publish_idempotent_and_member_denied(env):
    c,_,_=env
    p=project(env)
    card=create_card(env,[task_draft(env,title='计划修改')])
    assert card['checks']['valid']
    assert c.post(f'/api/cards/{card["id"]}/publish',headers=headers(env,'member1')).status_code==403
    r=c.post(f'/api/cards/{card["id"]}/publish',headers=headers(env))
    assert r.status_code==200,r.text
    assert c.post(f'/api/cards/{card["id"]}/publish',headers=headers(env)).json()['id']==r.json()['id']
    stale=create_card(env,[task_draft(env,title='过期修改')])
    c.patch(f'/api/projects/{p["id"]}/members/me',headers=headers(env),json={'skills':[],'weekly_hours':13})
    assert c.post(f'/api/cards/{stale["id"]}/publish',headers=headers(env)).status_code==409


def test_submission_history_materials_and_teacher_scope(env):
    c,_,app=env
    p=project(env)
    assert c.post(f'/api/projects/{p["id"]}/submissions',headers=headers(env),json={'stage_index':0,'summary':'无材料','artifact_urls':[],'file_ids':[]}).status_code==422
    payload={'stage_index':0,'summary':'阶段材料','artifact_urls':['https://example.com/docs'],'file_ids':[]}
    first=c.post(f'/api/projects/{p["id"]}/submissions',headers=headers(env),json=payload)
    assert first.status_code==200,first.text
    review=c.post(f'/api/submissions/{first.json()["id"]}/review',headers=headers(env,'teacher'),json={'result':'needs_changes','comment':'补充测试'})
    assert review.status_code==200
    second=c.post(f'/api/projects/{p["id"]}/submissions',headers=headers(env),json=payload).json()
    assert second['version']==2
    all_versions=c.get(f'/api/projects/{p["id"]}/submissions',headers=headers(env,'teacher')).json()
    assert len(all_versions)==2 and all_versions[0]['reviews'][0]['comment']=='补充测试'
    assert c.post(f'/api/submissions/{second["id"]}/review',headers=headers(env),json={'result':'passed','comment':'通过'}).status_code==403


def test_files_project_scope_and_teacher_only_submitted(env):
    c,_,_=env
    p=project(env)
    r=c.post(f'/api/projects/{p["id"]}/files',headers=headers(env,'member1'),files={'file':('../../材料.txt',b'demo','text/plain')})
    assert r.status_code==200,r.text
    fid=r.json()['id']
    listing=c.get(f'/api/projects/{p["id"]}/files',headers=headers(env))
    assert listing.status_code==200
    assert listing.json()[0]['id']==fid and 'storage_name' not in listing.json()[0]
    assert c.get(f'/api/projects/{p["id"]}/files',headers=headers(env,'member3')).status_code==403
    assert c.get(f'/api/projects/{p["id"]}/files',headers=headers(env,'teacher')).status_code==403
    assert c.get(f'/api/files/{fid}',headers=headers(env,'member3')).status_code==403
    assert c.get(f'/api/files/{fid}',headers=headers(env,'teacher')).status_code==403
    assert c.get(f'/api/files/{fid}',headers=headers(env)).content==b'demo'
    c.post(f'/api/projects/{p["id"]}/submissions',headers=headers(env),json={'stage_index':0,'summary':'附件','artifact_urls':[],'file_ids':[fid]})
    assert c.get(f'/api/files/{fid}',headers=headers(env,'teacher')).status_code==200


def test_unconfigured_agent_does_not_block_chat(env):
    c,_,_=env
    p=project(env)
    assert c.get('/api/config/status',headers=headers(env)).json()['ai_ready'] is False
    assert c.post(f'/api/projects/{p["id"]}/agent/analyze',headers=headers(env),json={'mode':'discussion'}).status_code==503
    assert c.post(f'/api/projects/{p["id"]}/messages',headers=headers(env),json={'content':'AI未配置仍可聊天','client_id':'offline'}).status_code==200
