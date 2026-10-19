from sqlalchemy import select
from .models import Member, User, Task


def fields(item, names):
    return {name:getattr(item,name) for name in names.split()}


def course_json(c,public=False):
    result=fields(c,'id teacher_id title description acceptance_criteria required_features optional_features references status version stages history')
    if public:
        result['history']=[h for h in c.history if h.get('snapshot',{}).get('status')=='published']
    return result


def member_json(db, m):
    u=db.get(User,m.user_id)
    return dict(fields(m,'user_id role skills weekly_hours'),name=u.name,username=u.username)


def project_json(db,p,user):
    members=db.scalars(select(Member).where(Member.project_id==p.id).order_by(Member.id)).all()
    return dict(fields(p,'id course_id name description status revision created_at'),
                role='teacher' if user.identity=='teacher' else next(m.role for m in members if m.user_id==user.id),
                members=[member_json(db,m) for m in members])


def requirement_json(r):
    return fields(r,'id project_id title description acceptance course_feature priority status creator_id created_at')


def task_json(t):
    return dict(fields(t,'id project_id title description requirement_id acceptance assignee_id estimated_hours remaining_hours dependencies start_date due_date status progress artifact_url blocker planning_risks stage_index creator_id created_at updated_at'),key=f'task_{t.id}')


def draft_json(t):
    return dict({k:v for k,v in task_json(t).items() if k not in ('id','project_id','creator_id','created_at','updated_at','planning_risks')},
                existing_id=t.id,dependencies=[f'task_{i}' for i in t.dependencies])


def current_tasks_json(db,project_id,checks=None):
    from .models import Project
    from .planning import check_plan
    if checks is None:
        checks=check_plan(db,db.get(Project,project_id),[],require_coverage=False)
    results=[]
    for task in db.scalars(select(Task).where(Task.project_id==project_id).order_by(Task.id)):
        data=task_json(task)
        data['planning_risks']=[v for v in checks['violations'] if data['key'] in v.get('task_keys',[])]
        results.append(data)
    return results


def comment_json(db,c):
    return dict(fields(c,'id task_id user_id kind content created_at'),author_name=db.get(User,c.user_id).name)


def message_json(db,m):
    return dict(fields(m,'id project_id user_id kind content created_at client_id related_type related_id supersedes_card_ids'),sender_name=db.get(User,m.user_id).name if m.user_id else 'Agent')


def card_json(c):
    return fields(c,'id project_id kind title summary questions source_message_ids supersedes_card_ids tasks checks status base_revision feedback creator_id created_at published_plan_id')


def plan_json(p):
    return fields(p,'id project_id version created_at created_by summary tasks changes')


def submission_json(s):
    return fields(s,'id project_id stage_index version status summary artifact_urls file_ids materials created_at created_by plan_version progress_snapshot reviews')


def file_json(f):
    return fields(f,'id project_id user_id filename content_type size created_at')
