from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from ..business import audit, bump_revision
from ..database import get_db
from ..models import Comment, Plan, Task, now
from ..permissions import require_project, resource
from ..planning import check_plan
from ..schemas import CommentInput, TaskInput, TaskPatch
from ..security import current_user
from ..serializers import comment_json, draft_json, task_json, current_tasks_json

router=APIRouter(prefix='/api',tags=['任务与评论'])
PLANNING_FIELDS={'title','description','requirement_id','acceptance','assignee_id','estimated_hours','dependencies','start_date','due_date','stage_index'}


def manual_plan(db,project,user,summary,changes):
    version=(db.scalar(select(func.max(Plan.version)).where(Plan.project_id==project.id)) or 0)+1
    db.flush()
    snapshots=current_tasks_json(db,project.id)
    after_by_id={t['id']:t for t in snapshots}
    changes=[dict(change,after=after_by_id[change['task_id']]) for change in changes]
    plan=Plan(project_id=project.id,version=version,created_by=user.id,summary=summary,tasks=snapshots,changes=changes)
    db.add(plan)
    project.status='active'


@router.get('/projects/{project_id}/tasks')
def list_tasks(project_id:int,db=Depends(get_db),user=Depends(current_user)):
    require_project(db,project_id,user)
    return current_tasks_json(db,project_id)


@router.post('/projects/{project_id}/tasks')
async def create_task(project_id:int,payload:TaskInput,request:Request,db=Depends(get_db),user=Depends(current_user)):
    p,_=require_project(db,project_id,user,leader=True)
    data=payload.model_dump(mode='json')
    draft=dict(data,key='manual_new',existing_id=None,dependencies=[f'task_{i}' for i in data['dependencies']])
    checks=check_plan(db,p,[draft],require_coverage=False)
    if not checks['valid']:
        raise HTTPException(422,checks)
    if data['status']=='done':
        data.update(progress=100,remaining_hours=0)
    task=Task(project_id=p.id,creator_id=user.id,**data)
    db.add(task)
    db.flush()
    bump_revision(db,p)
    audit(db,user.id,p.id,'task',task.id,'created',data)
    manual_plan(db,p,user,'组长手工创建任务',[{'task_id':task.id,'action':'created','after':task_json(task)}])
    db.commit()
    await request.app.state.hub.broadcast(p.id,{'type':'project_changed'})
    return task_json(task)


@router.patch('/tasks/{task_id}')
async def update_task(task_id:int,payload:TaskPatch,request:Request,db=Depends(get_db),user=Depends(current_user)):
    task=resource(db,Task,task_id)
    p,m=require_project(db,task.project_id,user,internal=True)
    changes=payload.model_dump(mode='json',exclude_unset=True)
    reason=changes.pop('correction_reason',None)
    if any(v is None for v in changes.values()):
        raise HTTPException(422,'任务字段不能设为 null')
    if m.role!='leader' and (task.assignee_id!=user.id or any(k in PLANNING_FIELDS for k in changes)):
        raise HTTPException(403,'成员只能更新本人任务的状态、进度、剩余工时、阻碍及成果')
    if task.status=='done' and changes:
        if m.role!='leader' or not reason or not reason.strip():
            raise HTTPException(409,'已完成任务的纠正需要组长提供 correction_reason，并保留审计记录')
    before=next(t for t in current_tasks_json(db,p.id) if t['id']==task.id)
    candidate=dict(draft_json(task),**changes)
    if 'dependencies' in changes:
        candidate['dependencies']=[f'task_{i}' for i in changes['dependencies']]
    # 完成记录只能通过本接口有理由纠正，模型草案不能改变它。
    planning_changed=any(k in PLANNING_FIELDS for k in changes)
    if task.status!='done' and planning_changed:
        checks=check_plan(db,p,[candidate],require_coverage=False)
        if not checks['valid']:
            raise HTTPException(422,checks)
    elif task.status=='done' and planning_changed:
        # 校验项目引用与排期：临时视作未完成，仅用于本次带原因的纠正。
        original_status=task.status
        task.status='todo'
        with db.no_autoflush:
            checks=check_plan(db,p,[candidate],require_coverage=False)
        task.status=original_status
        if not checks['valid']:
            raise HTTPException(422,checks)
    for k,v in changes.items():
        setattr(task,k,v)
    if task.status=='done':
        task.progress=100
        task.remaining_hours=0
    elif task.progress==100:
        raise HTTPException(422,'进度为 100 时任务状态须设为 done')
    task.updated_at=now()
    with db.no_autoflush:
        risk_checks=check_plan(db,p,[],require_coverage=False)
    task.planning_risks=[v for v in risk_checks['violations'] if not v.get('task_keys') or task_json(task)['key'] in v['task_keys']]
    bump_revision(db,p)
    audit(db,user.id,p.id,'task',task.id,'updated',{'before':before,'changes':changes,'reason':reason})
    if any(k in PLANNING_FIELDS for k in changes):
        manual_plan(db,p,user,reason or '组长手工调整计划',[{'task_id':task.id,'action':'updated','before':before,'after':task_json(task)}])
    adjust_needed=any(k in changes for k in ('progress','status','remaining_hours','blocker','due_date'))
    if adjust_needed:
        request.app.state.agent.enqueue(db,p.id,mode='adjust',requested=True)
    db.commit()
    if adjust_needed:
        request.app.state.agent.wake(p.id)
    await request.app.state.hub.broadcast(p.id,{'type':'project_changed'})
    return task_json(task)


@router.get('/tasks/{task_id}/comments')
def list_comments(task_id:int,db=Depends(get_db),user=Depends(current_user)):
    task=resource(db,Task,task_id)
    require_project(db,task.project_id,user,internal=True)
    return [comment_json(db,c) for c in db.scalars(select(Comment).where(Comment.task_id==task_id).order_by(Comment.id))]


@router.post('/tasks/{task_id}/comments')
async def create_comment(task_id:int,payload:CommentInput,request:Request,db=Depends(get_db),user=Depends(current_user)):
    task=resource(db,Task,task_id)
    p,_=require_project(db,task.project_id,user,internal=True)
    comment=Comment(task_id=task.id,user_id=user.id,**payload.model_dump())
    db.add(comment)
    db.flush()
    audit(db,user.id,p.id,'comment',comment.id,'created',payload.model_dump())
    db.commit()
    await request.app.state.hub.broadcast(p.id,{'type':'project_changed'})
    return comment_json(db,comment)
