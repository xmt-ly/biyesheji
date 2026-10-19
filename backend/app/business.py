from fastapi import HTTPException
from sqlalchemy import select, update
from .models import Audit, Card, Course, Project, Task
from .serializers import task_json, current_tasks_json


def audit(db, user_id, project_id, object_type, object_id, action, detail=None):
    db.add(Audit(user_id=user_id,project_id=project_id,object_type=object_type,object_id=object_id,
                 action=action,detail=detail or {}))


def bump_revision(db, project):
    db.execute(update(Project).where(Project.id==project.id).values(revision=Project.revision+1))
    db.execute(update(Card).where(Card.project_id==project.id, Card.status.in_(['pending','ready']))
               .values(status='stale'))


def validate_course(payload):
    stages=payload['stages']
    if stages:
        if len(stages)!=3:
            raise HTTPException(422,'课程需要按顺序设置三个检查阶段')
        deadlines=[s['deadline'] for s in stages]
        if not (deadlines[0]<deadlines[1]<deadlines[2]):
            raise HTTPException(422,'三个阶段截止日期必须严格递增')
    if payload['status']=='published':
        if not payload['description'].strip() or not payload['acceptance_criteria'].strip() or not payload['required_features'] or len(stages)!=3:
            raise HTTPException(422,'发布课程需要说明、课程验收标准、必做功能及三个检查阶段')
        if any(not s['deliverables'] or any(not d.strip() for d in s['deliverables']) for s in stages):
            raise HTTPException(422,'每个阶段必须设置交付物')


def progress_snapshot(db, project_id):
    from .planning import check_plan
    tasks=db.scalars(select(Task).where(Task.project_id==project_id).order_by(Task.id)).all()
    done=sum(t.status=='done' for t in tasks)
    planning_checks=check_plan(db,db.get(Project,project_id),[],require_coverage=True)
    return {'total':len(tasks),'done':done,'completion_percent':round(done*100/len(tasks),1) if tasks else 0,
            'calculation':'当前项目已完成任务数 / 全部任务数；不等同功能验收或成员贡献',
            'tasks':current_tasks_json(db,project_id,checks=planning_checks),
            'planning_checks':planning_checks}
